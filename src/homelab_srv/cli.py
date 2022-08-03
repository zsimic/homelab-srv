"""
For more info see https://github.com/zsimic/homelab-srv

\b
Example:
    stop                # To stop all services
    stop syncthing      # To stop one service
    stop rps:syncthing  # To stop one service, on one host
"""

import logging
import os
import re
from collections import defaultdict
from pathlib import Path

import click
import runez
from runez.render import PrettyTable

import homelab_srv
from homelab_srv import CONFIG_PATH, GSRV, HomelabSite, read_yml, run_rsync, run_ssh, run_uncaptured, SITE_SPEC_YML, SITE_YML, SRV_RUN


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
                run_ssh(hostname, homelab_srv.SCRIPT_NAME, self.command, self.given, *args)


def target_option():
    return click.argument("target", callback=CliTarget(), required=False)


def get_hostname():
    cmd = "/bin/hostname"
    return runez.run(cmd, dryrun=False, logger=None).output if os.path.exists(cmd) else os.environ.get("COMPUTERNAME") or ""


def base_from_spec(candidate, selected_site):
    path = Path(candidate) / SITE_SPEC_YML
    if path.exists():
        cfg = read_yml(path)
        if not cfg:
            logging.warning("File '%s' is not valid yaml" % path)
            return None, selected_site

        sites = runez.flattened(cfg.get("sites"), keep_empty=None, split=",")
        if not sites:
            logging.warning("File '%s' does not define any 'sites:'" % path)
            return None, selected_site

        if not selected_site:
            selected_site = sites[0]

        if selected_site not in sites:
            logging.warning("Site '%s' is not defined in %s" % (selected_site, path))

        return path, selected_site

    return None, selected_site


def find_base_folder(path=None, site=None) -> (Path, str):
    if not runez.DEV.current_test():  # pragma: no cover
        if SRV_RUN.is_dir():
            return SRV_RUN, None, None

        local_site = Path(".") / SITE_YML
        local_sites = Path("..") / SITE_SPEC_YML
        if local_sites.exists() and local_site.exists():
            return local_site.absolute().resolve().parent, "cwd", local_site.name

        for line in runez.readlines(CONFIG_PATH, first=1):
            path, site = base_from_spec(os.path.expanduser(line), site)
            if path:
                return path, CONFIG_PATH, site

            logging.warning("Path configured in %s is invalid: %s" % (CONFIG_PATH, path))

    path, site = base_from_spec(path or os.getcwd(), site)
    if path:
        logging.info("Using spec from current working dir: %s" % path)
        return path, "cwd", site

    return None, None, site


@runez.click.group(epilog=__doc__)
@click.pass_context
@runez.click.version(prog_name=homelab_srv.SCRIPT_NAME, version=homelab_srv.__version__)
@runez.click.debug()
@runez.click.dryrun("-n")
@runez.click.color()
@click.option("--simulate", "-s", help="Simulate a hostname, for troubleshooting/test runs")
def main(ctx, debug, simulate):
    """Manage dockerized servers"""
    runez.system.AbortException = SystemExit
    runez.log.setup(debug=debug, level=logging.INFO, console_format="%(levelname)s %(message)s", default_logger=logging.info)
    GSRV.is_executor = None
    GSRV.hostname = None
    path = site = None
    if simulate:
        assert runez.DRYRUN
        if ":" in simulate:
            GSRV.is_executor = True
            site, _, GSRV.hostname = simulate.partition(":")

        elif "@" in simulate:
            GSRV.is_executor = True
            site, _, path = simulate.partition("@")

    path, origin, site = find_base_folder(path=path, site=site)
    GSRV.bcfg = HomelabSite(path, origin, site)
    if GSRV.is_executor is None:
        GSRV.is_executor = GSRV.bcfg.folder is SRV_RUN

    if not GSRV.hostname:
        GSRV.hostname = get_hostname()

    if ctx.invoked_subcommand not in ("blocklist", "meta"):
        fatal = 0
        for item, msg in GSRV.bcfg.sanity_check():
            if "should" in msg or "would" in msg:
                logging.warning("%s: %s" % (item, msg))

            else:
                fatal += 1
                logging.error("%s: %s" % (item, msg))

        if fatal:
            runez.abort("Please fix reported issues first")


RX_BLOCKLIST_LINE = re.compile(r"^([0-9:.]+\s+)?(.+)$")
RX_IP = re.compile(r"^[0-9.]+$")
RX_VALID_HOST_PART = re.compile(r"^(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)


def is_valid_hostname(hostname):
    if not hostname or len(hostname) > 255 or "." not in hostname:
        return False

    return all(RX_VALID_HOST_PART.match(x) for x in hostname.split("."))


def analyze_blocklist(folder):
    result = defaultdict(int)
    ips = set()
    invalid_hosts = set()
    for fname in os.listdir(folder):
        path = os.path.join(folder, fname)
        for line_number, line in enumerate(runez.readlines(path)):
            line, _, _ = line.partition("#")
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            m = RX_BLOCKLIST_LINE.match(line)
            if not m:
                print("--> invalid line %s: %s" % (line_number, line))

            hostnames = m.group(2).split(" ")
            for hostname in hostnames:
                if hostname in ("local", "localhost"):
                    continue

                if ":" in hostname or RX_IP.match(hostname):
                    ips.add(hostname)
                    continue

                if not is_valid_hostname(hostname):
                    if "_" not in hostname:
                        invalid_hosts.add(hostname)
                        # print("--> invalid host line %s:%s: %s" % (path, line_number, hostname))

                result[hostname] += 1

    multi = {k: v for k, v in result.items() if v > 1}
    print("%s: %s hostnames, %s appear multiple times" % (folder, len(result), len(multi)))
    return result


@main.command()
@click.argument("spec", required=False)
def blocklist(spec):
    if not spec:
        spec = runez.DEV.project_path("curated-blocklist.yml")

    if not os.path.isfile(spec):
        runez.abort("")

    ads = analyze_blocklist("_tmp/ads")
    malicious = analyze_blocklist("_tmp/malicious")
    sus = analyze_blocklist("_tmp/sus")
    overall = defaultdict(int)
    for d in (ads, malicious, sus):
        for k, v in d.items():
            overall[k] += v

    multi = {k: v for k, v in overall.items() if v > 1}
    print("\noverall: %s hostnames, %s appear multiple times" % (len(overall), len(multi)))


@main.command()
@click.argument("domain", required=False)
def certbot(domain):
    """Auto-update certbot SSL certs"""
    from homelab_srv.cert import CertbotRunner

    m = CertbotRunner()
    m.update_certs(domain)


@main.command()
@target_option()
def logs(target):
    """Show logs for specified container"""
    target.run()


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
    """Configure where your homelab-srv config is"""
    GSRV.require_orchestrator()
    if not folder:
        cfg_loc = runez.dim("(in %s)" % CONFIG_PATH)
        if GSRV.bcfg.folder_origin == CONFIG_PATH:  # pragma: no cover
            print("Currently configured folder %s: %s" % (cfg_loc, runez.bold(runez.short(GSRV.bcfg.folder))))

        else:
            print("%s is currently configured %s" % (runez.red("No folder"), cfg_loc))

        return

    folder = Path(folder).absolute()
    if not folder.is_dir():
        runez.abort("Folder '%s' does not exist" % folder)

    cfg_yml = folder / SITE_SPEC_YML
    if not cfg_yml.exists():
        runez.abort("'%s' does not exist" % cfg_yml)

    runez.write(CONFIG_PATH, "%s\n" % folder)


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
        run_uncaptured("ssh-keygen", "-R", address.rpartition("@")[2])
        r = runez.run("ssh", *test_args, fatal=False)

    if r.succeeded:
        print("ssh %s %s" % (address, runez.green("already works")))
        return

    if "denied" not in r.error:
        runez.abort("%s doesn't seem reachable:\n%s" % (address, r.full_output))

    print(runez.orange("\nSeeding ssh id...\n"))
    run_uncaptured("ssh-copy-id", "-i", key, address)


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
        run_ssh(hostname, homelab_srv.SCRIPT_NAME, "--color", "ps")


def push_srv_to_host(hostname, self_upgrade):
    GSRV.require_orchestrator()
    if self_upgrade:
        run_ssh(hostname, "/usr/local/bin/pickley", "install", "https://github.com/zsimic/homelab-srv.git")

    run_rsync(GSRV.bcfg.folder, "%s:%s" % (hostname, SRV_RUN.as_posix()))


@main.command()
@click.option("--self-upgrade", "-u", is_flag=True, help="Upgrade homelab-srv as well")
@click.argument("hosts", required=False)
def push(self_upgrade, hosts):
    """Push srv setup to remote hosts"""
    hosts = runez.flattened(hosts, keep_empty=None, split=",")
    if not hosts or hosts == "all":
        hosts = GSRV.bcfg.run.hostnames

    for hostname in hosts:
        push_srv_to_host(hostname, self_upgrade)


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
@target_option()
def stop(target):
    """Stop target(s)"""
    target.run()


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
