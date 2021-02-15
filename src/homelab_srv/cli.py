"""
For more info see https://github.com/zsimic/homelab-srv

\b
Example:
    stop                # To stop all services
    stop syncthing      # To stop one service
    stop rps:syncthing  # To stop one service, on one host
"""

import logging
from pathlib import Path

import click
import runez
from runez.render import PrettyTable

from homelab_srv import __version__, C, GSRV, run_rsync


class CliTarget:

    def __call__(self, ctx, _param, value):
        self.command = ctx.command.name
        self.given = value
        self.hosts = None
        if value:
            self.hosts, _, self.given = value.rpartition(":")

        self.dcs = GSRV.bcfg.get_dcs(self.given)
        if GSRV.is_executor:
            if self.hosts and self.hosts != GSRV.hostname:
                raise click.BadParameter("Target host on executor must be self")

            return self

        self.hosts = GSRV.bcfg.get_hosts(self.hosts)
        return self

    def run(self):
        if GSRV.is_executor:
            should_run = GSRV.bcfg.run.dc_names_for_host(GSRV.hostname) or []
            for dc in self.dcs:
                if dc.dc_name not in should_run:
                    logging.info("'%s' is not configured to run on host '%s'" % (dc.dc_name, GSRV.hostname))

                else:
                    f = getattr(dc, self.command)
                    f()

        else:
            for hostname in self.hosts:
                runez.run("ssh", hostname, C.SCRIPT_NAME, self.command, self.given)


def target_option():
    return click.argument("target", callback=CliTarget(), required=False)


@runez.click.group(epilog=__doc__)
@click.pass_context
@runez.click.version(prog_name=C.SCRIPT_NAME, version=__version__)
@runez.click.debug()
@runez.click.dryrun("-n")
@runez.click.color()
@click.option("--simulate", "-s", help="Simulate a role:host, for troubleshooting/test runs")
def main(ctx, debug, simulate):
    """Manage dockerized servers"""
    runez.system.AbortException = SystemExit
    runez.log.setup(debug=debug, level=logging.INFO)
    if simulate:
        runez.log.set_dryrun(True)
        role, _, host = simulate.rpartition(":")
        if role:
            GSRV.is_executor = role.startswith("e")

        if host:
            GSRV.hostname = host

    if ctx.invoked_subcommand != "meta":
        fatal = 0
        for item, msg in GSRV.bcfg.sanity_check():
            if "should" in msg or "would" in msg:
                logging.warning("%s: %s" % (item, msg))

            else:
                fatal += 1
                logging.error("%s: %s" % (item, msg))

        if fatal:
            runez.abort("Please fix reported issues first")


@main.group()
def meta():
    """Meta/utility subcommands"""


@meta.command()
@click.argument("pwd", required=False)
def mkpass(pwd):
    """Create an ansible-compatible salted password"""
    import crypt
    import getpass

    GSRV.require_orchestrator()
    if not pwd:  # pragma: no cover
        pwd = getpass.getpass()

    salt = crypt.mksalt(crypt.METHOD_SHA512)
    print(crypt.crypt(pwd, salt))


@meta.command()
@click.option("--by-service", "-s", is_flag=True, help="Show ports used by service")
def ports(by_service):
    """Show ports used on host by all docker-compose files combined"""
    table = PrettyTable(2, border="colon")
    ports = GSRV.bcfg.used_host_ports(by_port=not by_service)
    for port, dc_names in sorted(ports.items()):
        dc_names = sorted(dc_names)
        names = runez.joined(dc_names)
        if not by_service and len(dc_names) > 1:
            names = runez.red(names)

        table.add_row(port, names)

    print(table)


@meta.command()
@click.argument("folder", required=False)
def set_folder(folder):
    """Configure where your _config.yml is"""
    GSRV.require_orchestrator()
    if not folder:
        cfg_loc = runez.dim("(in %s)" % C.CONFIG_PATH)
        if GSRV.bcfg.folder_origin == C.CONFIG_PATH:  # pragma: no cover
            print("Currently configured folder %s: %s" % (cfg_loc, runez.bold(runez.short(GSRV.bcfg.folder))))

        else:
            print("%s is currently configured %s" % (runez.red("No folder"), cfg_loc))

        return

    folder = Path(folder).absolute()
    if not folder.is_dir():
        runez.abort("Folder '%s' does not exist" % folder)

    cfg_yml = folder / C.CONFIG_YML
    if not cfg_yml.exists():
        runez.abort("'%s' does not exist" % cfg_yml)

    runez.write(C.CONFIG_PATH, "%s\n" % folder)


@meta.command()
@target_option()
def status(target: CliTarget):
    """Show current status"""
    table = PrettyTable(2, border="colon")
    table.header[1].style = "bold"
    folder = runez.short(GSRV.bcfg.folder.as_posix()) if GSRV.bcfg.folder else "-not configured-"
    if GSRV.bcfg.folder_origin:
        folder += runez.dim(" (from: %s)" % GSRV.bcfg.folder_origin)

    table.add_row("Base", folder)
    role = "[executor]" if GSRV.is_executor else "[orchestrator]"
    hostname = "%s %s" % (GSRV.hostname, runez.brown(role))
    if runez.DRYRUN:
        hostname += runez.dim(" [dry-run]")

    table.add_row("Hostname", hostname)
    if GSRV.is_orchestrator:
        table.add_row("Hosts", runez.joined(target.hosts))

    table.add_row("DCs", runez.joined(target.dcs))
    print(table)


@main.group()
def cert():
    """Manage certs"""


@cert.command()
@click.argument("domain")
def update(domain):
    """Update certs for a domain"""


@main.command()
@click.argument("hosts", required=False)
def push(hosts):
    """Push srv setup to remote hosts"""
    GSRV.require_orchestrator()
    hosts = runez.flattened(hosts, keep_empty=None, split=",")
    if not hosts or hosts == "all":
        hosts = GSRV.bcfg.run.hostnames

    for hostname in hosts:
        run_rsync(GSRV.bcfg.folder, "%s:%s" % (hostname, C.SRV_RUN.as_posix()))


@main.command()
@target_option()
def start(target):
    """Start target(s)"""
    target.run()


@main.command()
@target_option()
def stop(target):
    """Stop target(s)"""
    target.run()


@main.command()
@target_option()
def upgrade(target):
    """Upgrade target(s)"""
    target.run()


@main.command()
@target_option()
def backup(target):
    """Backup persisted files"""
    target.run()


@main.command()
@target_option()
def restore(target):
    """Restore back-up files"""
    target.run()


if __name__ == "__main__":  # pragma: no cover
    main()
