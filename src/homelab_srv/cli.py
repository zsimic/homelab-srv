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

from homelab_srv import __version__, C, GSRV


def colored_port(port):
    if port in GSRV.bcfg.conflicting_ports:
        return runez.red(port)

    if port < 1000:
        return runez.blue(port)

    return str(port)


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

    def run(self, *args, **kwargs):
        if GSRV.is_executor:
            should_run = GSRV.bcfg.run.dc_names_for_host(GSRV.hostname) or []
            for dc in self.dcs:
                if dc.dc_name not in should_run:
                    logging.info("'%s' is not configured to run on host '%s'" % (dc.dc_name, GSRV.hostname))

                else:
                    f = getattr(dc, self.command)
                    f(*args, **kwargs)

            return

        args = list(args)
        for k, v in kwargs.items():
            if v is not None:
                if isinstance(v, bool):
                    if v:
                        args.append("--%s" % k)

                else:  # pragma: no cover
                    args.append("--%s=%s" % (k, v))

        for hostname in self.hosts:
            should_run = GSRV.bcfg.run.dc_names_for_host(hostname) or []
            if any(dc.dc_name in should_run for dc in self.dcs):
                C.run_ssh(hostname, C.SCRIPT_NAME, self.command, self.given, *args)


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
    runez.log.setup(debug=debug, level=logging.INFO, console_format="%(levelname)s %(message)s", default_logger=logging.info)
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
@click.option("--ports", "-p", is_flag=True, help="Show used ports across all docker-compose files")
@target_option()
def status(ports, target: CliTarget):
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

    table.add_row("Selected", runez.joined(target.dcs))
    print(table)

    if ports:
        print("")
        table = PrettyTable(["Port", "Service(s)"], border="reddit")
        table.header.style = "bold"
        for port, names in sorted(GSRV.bcfg.used_host_ports(by_port=True).items()):
            names = runez.joined(sorted(names))
            if port in GSRV.bcfg.conflicting_ports:
                names = runez.red(names)

            table.add_row(colored_port(port), names)

        print(table)
        print("")

        table = PrettyTable(["Service", "Port(s)"], border="reddit")
        table.header.style = "bold"
        for name, values in sorted(GSRV.bcfg.used_host_ports(by_port=False).items()):
            table.add_row(name, runez.joined(colored_port(p) for p in sorted(values)))

        print(table)


@main.group()
def seed():
    """Seed remote host setup (ssh, homelab-srv etc)"""


@seed.command()
@click.option("--key", default="~/.ssh/id_rsa.pub", help="Public key to seed target with")
@click.argument("address")
def ssh(key, address):
    """Seed remote user@host with given ssh public key"""
    key = Path(key).expanduser()
    if not key.exists():
        runez.abort("Key '%s' does not exist" % key)

    test_args = ["-n", "-o", "PreferredAuthentications=publickey", address, "echo", "hi"]
    r = runez.run("ssh", *test_args, fatal=False)
    if r.failed and "IDENTIFICATION HAS CHANGED" in r.error:
        C.run_uncaptured("ssh-keygen", "-R", address.rpartition("@")[2])
        r = runez.run("ssh", *test_args, fatal=False)

    if r.succeeded:
        print("ssh %s %s" % (address, runez.green("already works")))
        return

    if "denied" not in r.error:
        runez.abort("%s doesn't seem reachable:\n%s" % (address, r.full_output))

    print(runez.orange("\nSeeding ssh id...\n"))
    C.run_uncaptured("ssh-copy-id", "-i", key, address)


@seed.command()
@click.argument("hostname")
def setup(hostname):
    """Seed homelab-srv itself on remote host"""
    C.run_ssh(hostname, "/usr/local/bin/pickley", "install", "https://github.com/zsimic/homelab-srv.git")
    push_srv_to_host(hostname)


@main.group()
def cert():
    """Manage certs"""


@cert.command()
@click.argument("domain")
def update(domain):
    """Update certs for a domain"""


@main.command()
def ps():
    """Show running docker services"""
    if GSRV.is_executor:
        table = PrettyTable([runez.blue(GSRV.hostname), "Running", "Created"], border="dots")
        dc_names = GSRV.bcfg.run.dc_names_for_host(GSRV.hostname) or []
        for dc_name in sorted(dc_names):
            dc = GSRV.bcfg.dc_files.get(dc_name)
            if dc:
                info = dc.is_running
                running = runez.dim("not running")
                created = ""
                if info:
                    running = runez.bold(info["STATUS"])
                    created = runez.dim(info["CREATED"])

                table.add_row(dc.dc_name, running, created)

        print(table)
        return

    for hostname in GSRV.bcfg.run.hostnames:
        C.run_ssh(hostname, C.SCRIPT_NAME, "--color", "ps")


def push_srv_to_host(hostname):
    GSRV.require_orchestrator()
    C.run_rsync(GSRV.bcfg.folder, "%s:%s" % (hostname, C.SRV_RUN.as_posix()))


@main.command()
@click.argument("hosts", required=False)
def push(hosts):
    """Push srv setup to remote hosts"""
    hosts = runez.flattened(hosts, keep_empty=None, split=",")
    if not hosts or hosts == "all":
        hosts = GSRV.bcfg.run.hostnames

    for hostname in hosts:
        push_srv_to_host(hostname)


@main.command()
@target_option()
def restart(target):
    """Restart target(s)"""
    target.run()


@main.command()
@target_option()
def start(target):
    """Start target(s)"""
    target.run()


@main.command()
@click.option("--down", "-d", is_flag=True, help="Use 'docker-compose down' instead of simple stop")
@target_option()
def stop(down, target):
    """Stop target(s)"""
    target.run(down=down)


@main.command()
@click.option("--force", "-f", is_flag=True, help="Force upgrade, even if no new image available")
@target_option()
def upgrade(force, target: CliTarget):
    """Upgrade target(s)"""
    target.run(force=force)


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
