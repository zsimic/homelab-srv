import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Union

import runez
import yaml


__version__ = "0.0.1"
CONFIG_PATH = "~/.config/homelab-srv.conf"
SCRIPT_NAME = "homelab-srv"
DEFAULT_BACKUP_FOLDER = "/srv/data/server-backup"
SRV = Path("/srv")
SRV_PERSIST = SRV / "persist"
SRV_RUN = SRV / "run"
SRV_SSL = SRV / "ssl"
CONFIG_YML = "_config.yml"
SITE_SPEC_YML = "_sites.yml"
SITE_YML = "_site.yml"
SPECIAL_DOCKER_COMPOSE_NAME = ["syncthing"]


class GlobalState:
    """Global config, loaded once-per run in main()"""

    def __repr__(self):
        return "%s" % self.bcfg

    bcfg = None  # type: HomelabSite
    hostname = None
    is_executor = False  # True if this host is supposed to run docker services
    site = None  # Name of site currently selected

    @property
    def is_orchestrator(self):
        """True if this host is NOT supposed to run docker services, but remotely manage other servers instead"""
        return not self.is_executor

    def require_orchestrator(self):
        if not self.is_orchestrator:
            runez.abort("This command can only be ran from orchestrator machine")


GSRV = GlobalState()


class HomelabSite:
    """Config as defined by {folder}/_(config|site).yml"""

    def __init__(self, folder, folder_origin=None, site=None):
        if folder:
            if not isinstance(folder, Path):
                folder = Path(folder)

            if folder.name == SITE_SPEC_YML:
                folder = folder.parent

            if site:
                folder = folder / site

        self.folder = folder
        self.folder_origin = folder_origin
        self.site = site
        self.cfg_yml = self.folder and (self.folder / SITE_YML)
        self.cfg = read_yml(self.cfg_yml) or {}
        self.dc_files = {}  # type: dict[str, SYDC]
        self.yaml_key = "%s:" % SITE_YML
        if site:
            self.yaml_key = "%s/%s" % (site, self.yaml_key)

        if self.folder and self.folder.is_dir():
            for fname in self.folder.glob("*.yml"):
                if not fname.name.startswith("_"):
                    dc = SYDC(self, fname)
                    self.dc_files[dc.dc_name] = dc

            for fname in folder.glob("*/docker-compose.yml"):
                dc = SYDC(self, fname)
                self.dc_files[dc.dc_name] = dc

        self.env = self.cfg.get("env")
        self.run = SYRun(self)
        self.backup = SYBackup(self)

    def __repr__(self):
        return self.yaml_key

    def get_dcs(self, names=None):
        dcs = list(self.dc_files.values())
        if names in ("all", "*"):
            return dcs

        if names == "special":
            return [x for x in dcs if x.is_special]

        if names == "vanilla":
            return [x for x in dcs if x.vanilla_backup]

        if not names:
            return [x for x in dcs if not x.is_special]

        names = runez.flattened(names, keep_empty=None, split=",")
        bad_refs = [x for x in names if x not in self.dc_files]
        if bad_refs:
            runez.abort("Unknown docker-compose refs: %s" % ", ".join(bad_refs))

        return [x for x in dcs if x.dc_name in names]

    def get_hosts(self, names=None):
        if not names or names in ("all", "*"):
            return self.run.hostnames

        names = runez.flattened(names, keep_empty=None, split=",")
        bad_refs = [x for x in names if x not in self.run.hostnames]
        if bad_refs:
            runez.abort("Host(s) not configured: %s" % ", ".join(bad_refs))

        return names

    def dc_name_check(self, names, origin):
        if names:
            for name in names:
                if name not in self.dc_files:
                    yield self, "DC definition '%s' does not exist (referred from %s)" % (name, origin)

    @runez.cached_property
    def conflicting_ports(self):
        return {k: v for k, v in self.used_host_ports().items() if len(v) > 1}

    def used_host_ports(self, by_port=True):
        result = defaultdict(set)
        for dc in self.dc_files.values():
            for s in dc.services.values():
                if s.ports and s.ports.host_side:
                    for port in s.ports.host_side:
                        port = int(port)
                        if by_port:
                            result[port].add(dc.dc_name)

                        else:
                            result[dc.dc_name].add(port)

        return result

    def sanity_check(self):
        if not self.folder:
            yield self, "Run this to configure where your '%s' is: %s set-folder PATH" % (SITE_SPEC_YML, SCRIPT_NAME)
            return

        if not self.cfg_yml.exists():
            yield self, "%s does not exist" % self.cfg_yml
            return

        if not self.dc_files:
            yield self, "%s has no docker-compose files defined" % self.folder

        for dc in self.dc_files.values():
            yield from dc.sanity_check()

        for port, dc_names in self.conflicting_ports.items():
            yield self, "Port %s would conflict on same host for dcs: %s" % (port, " ".join(dc_names))

        yield from self.run.sanity_check()
        yield from self.backup.sanity_check()


def read_yml(path: Path, default=None):
    if path and path.exists():
        with open(path) as fh:
            return yaml.load(fh, Loader=yaml.BaseLoader)

    return default


def run_docker(*args):
    assert GSRV.is_executor
    return runez.run("docker", *args, stdout=None, stderr=None)


def run_rsync(src, dest, sudo=False, env=None):
    cmd = []
    if sudo:
        cmd.append("sudo")

    cmd.append("rsync")
    cmd.append("-rlptJ")
    cmd.append("--delete")
    if env and "PUID" in env and "PGID" in env:
        cmd.append("--chown=%s:%s" % (env["PUID"], env["PGID"]))

    need_trail = os.path.isdir(src)
    src = str(src)
    dest = str(dest)
    assert len(src) > 7
    assert len(dest) > 7
    if ":" not in str(dest):
        runez.ensure_folder(dest if need_trail else os.path.dirname(dest), logger=logging.info)

    src = slash_trail(src, trail=need_trail)
    dest = slash_trail(dest, trail=need_trail)
    run_uncaptured(*cmd, src, dest)


def run_ssh(hostname, *args):
    GSRV.require_orchestrator()
    if hostname not in GSRV.bcfg.run.hostnames:
        runez.abort("Host '%s' is not defined in config %s" % (hostname, runez.short(GSRV.bcfg.cfg_yml)))

    run_uncaptured("ssh", hostname, *args)


def run_uncaptured(program, *args):
    runez.run(str(program), *args, stdout=None, stderr=None, logger=logging.info)


def slash_trail(path, trail=False):
    path = path.rstrip("/")
    return "%s/" % path if trail else path


class DCItem:
    """Common things across docker-compose definitions we're working with"""

    def __init__(self, parent: Union[HomelabSite, "DCItem"], cfg=None, key=None):
        self.parent = parent
        self.yaml_key = key or self.__class__.__name__[2:].lower()
        self.cfg = cfg if cfg is not None else parent.cfg.get(self.yaml_key, {})  # type: dict

    def __repr__(self):
        result = ""
        parent = self
        while parent:
            key = getattr(parent, "yaml_key", None)
            if key:
                sep = "" if not result or key[-1] in ":/" else "/"
                result = "%s%s%s" % (key, sep, result)

            parent = getattr(parent, "parent", None)

        return result

    def _parent_of_type(self, t):
        parent = self
        while parent:
            if isinstance(parent, t):
                return parent

            parent = getattr(parent, "parent", None)

    @runez.cached_property
    def dc_file(self) -> "SYDC":
        return self._parent_of_type(SYDC)

    @runez.cached_property
    def dc_config(self) -> HomelabSite:
        return self._parent_of_type(HomelabSite)


class DCEnvironment(DCItem):

    @runez.cached_property
    def by_name(self) -> Dict[str, str]:
        result = {}
        if self.cfg:
            for val in self.cfg:
                name, _, value = val.partition("=")
                result[name] = value.strip()

        return result

    def sanity_check(self):
        env = self.dc_config.env
        if env:
            for k, expected_value in env.items():
                v = self.by_name.get(k)
                if v is not None and v != expected_value:
                    yield self, "%s should be %s (instead of %s)" % (k, expected_value, v)


class DCPorts(DCItem):

    @runez.cached_property
    def host_side(self):
        result = {}
        if self.cfg:
            for val in self.cfg:
                a, _, b = val.partition(":")
                result[a] = b

        return result


class DCVolumes(DCItem):

    @runez.cached_property
    def volumes(self):
        result = {}
        if self.cfg:
            for vol in self.cfg:
                a, _, b = vol.partition(":")
                result[a] = b

        return result

    @runez.cached_property
    def vanilla_backup(self):
        n = 0
        expected_parts = (SRV_PERSIST / self.dc_file.dc_name).parts
        part_count = len(expected_parts)
        for vol in self.volumes:
            vol_parts = Path(vol).parts
            if len(vol_parts) >= part_count and vol_parts[:part_count] == expected_parts:
                n += 1

        return n == len(self.volumes)


class DCService(DCItem):

    def __init__(self, parent, service_name, cfg):
        super().__init__(parent, cfg=cfg, key=service_name)
        self.service_name = service_name
        self.image = cfg.get("image")
        self.environment = DCEnvironment(self)
        self.ports = DCPorts(self)
        self.restart = cfg.get("restart")
        self.volumes = DCVolumes(self)

    def sanity_check(self):
        yield from self.environment.sanity_check()


class SYRun(DCItem):
    """'run:' entry in _site.yml"""

    def __init__(self, parent):
        super().__init__(parent)
        self.dcs_by_host = {k: runez.flattened(v, keep_empty=None, split=" ") for k, v in self.cfg.items()}

    def dc_names_for_host(self, hostname):
        return self.dcs_by_host.get(hostname)

    @runez.cached_property
    def hostnames(self):
        return list(self.dcs_by_host.keys())

    def sanity_check(self):
        if not self.hostnames:
            yield self, "no hosts are defined in %s run: section" % self

        for hostname, dc_names in self.dcs_by_host.items():
            yield from self.dc_config.dc_name_check(dc_names, "%s/%s" % (self, hostname))


class SYBackup(DCItem):
    """'backup:' entry in _site.yml"""

    def __init__(self, parent):
        super().__init__(parent)
        self.folder = self.cfg.get("folder", DEFAULT_BACKUP_FOLDER)
        self.per_host = runez.flattened(self.cfg.get("per_host"), keep_empty=None, split=" ")
        self.restrict = self.cfg.get("restrict", {})

    def backup_destination(self, dc: "SYDC"):
        dest = Path(self.folder)
        if dc.dc_name in self.per_host:
            dest = dest / GSRV.hostname

        return dest / dc.dc_name

    def sanity_check(self):
        yield from self.dc_config.dc_name_check(self.per_host, "%s/per_host" % self)
        yield from self.dc_config.dc_name_check(self.restrict, "%s/restrict" % self)


class SYDC(DCItem):
    """Info from one docker-compose.yml file"""

    def __init__(self, parent, dc_path: Path):
        self.parent = parent
        self.dc_path = dc_path
        self.dc_name = dc_path.parent.name if dc_path.name == "docker-compose.yml" else dc_path.stem
        self.is_special = self.dc_name in SPECIAL_DOCKER_COMPOSE_NAME
        cfg = read_yml(dc_path) or {}
        super().__init__(parent, cfg=cfg.get("services", {}), key=self.dc_name)
        self.services = {}
        for k, v in self.cfg.items():
            service = DCService(self, k, v)
            self.services[service.service_name] = service

    def __repr__(self):
        return self.dc_name

    def sanity_check(self):
        for s in self.services.values():
            yield from s.sanity_check()

    def run_docker_compose(self, *args):
        run_uncaptured("docker-compose", "-p", self.dc_name, "-f", self.dc_path, *args)

    @property
    def is_running(self):
        for image in self.images:
            status = self.running_docker_images.get(image)
            if status:
                return status

    @runez.cached_property
    def running_docker_images(self):
        r = runez.run("docker", "ps", logger=None)
        info = runez.parsed_tabular(r.output.strip().replace("CONTAINER ID", "CONTAINER_ID"))
        return {x["IMAGE"]: x for x in info}

    @runez.cached_property
    def images(self):
        return [s.image for s in self.services.values()]

    @runez.cached_property
    def vanilla_backup(self):
        if self.services:
            for service in self.services.values():
                if not service.volumes or not service.volumes.vanilla_backup:
                    return False

            return True

    def backup(self, invert=False, auto=False):
        assert GSRV.is_executor
        action = "restoring" if invert else "backing up"
        if self.is_special:
            if not auto:
                logging.debug("Not %s '%s': special container" % (action, self.dc_name))

            return

        if not self.vanilla_backup:
            if not auto:
                logging.debug("Not %s '%s': it does NOT use volume %s/%s" % (action, self.dc_name, SRV_PERSIST, self.dc_name))

            return

        configured = self.parent.backup.restrict.get(self.dc_name)
        configured = runez.flattened(configured, keep_empty=None, split=" ")
        if not configured:
            configured = [""]

        logging.debug("%s %s, configured: %s" % (action, self.dc_name, configured))
        backup_dest = self.parent.backup.backup_destination(self)
        env = self.dc_config.env
        for rel_path in configured:
            src = SRV_PERSIST / self.dc_name / rel_path
            dest = backup_dest / rel_path
            if invert:
                env = None
                src, dest = dest, src

            logging.debug("%s source: %s [exists: %s], dest: %s" % (action, src, src.exists(), dest))
            if runez.DRYRUN or src.exists():
                if not auto or not dest.exists():
                    run_rsync(src, dest, sudo=True, env=env)

    def pull_images(self):
        """Using docker pull, apparently no way to see if docker-compose pull got a new image or not..."""
        updated = 0
        for image in self.images:
            r = runez.run("docker", "pull", image)
            if runez.DRYRUN or "newer image" in r.full_output:
                updated += 1

        return updated

    def logs(self):
        assert GSRV.is_executor
        self.run_docker_compose("logs")

    def restore(self, auto=False):
        self.backup(invert=True, auto=auto)

    def restart(self):
        assert GSRV.is_executor
        self.run_docker_compose("restart")

    def start(self):
        assert GSRV.is_executor
        self.run_docker_compose("start")

    def stop(self, down=False):
        assert GSRV.is_executor
        self.run_docker_compose("down" if down else "stop")
        self.backup()

    def upgrade(self, force=False):
        assert GSRV.is_executor
        updated = self.pull_images()
        if not force and not updated and self.is_running:  # pragma: no cover
            print("No new docker image available for %s" % self.dc_name)
            return

        self.run_docker_compose("down")
        self.backup()
        run_docker("image", "prune", "-f")
        self.run_docker_compose("up", "-d")
