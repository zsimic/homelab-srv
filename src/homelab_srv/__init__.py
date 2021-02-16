import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Union

import runez
import yaml


__version__ = "0.0.1"


class C:
    """
    Global state and constants

    Allows to avoid having to 'import' them one by one...
    Using 'C.' for constants, and 'GSRV.' for all other cached props
    """

    CONFIG_PATH = "~/.config/homelab-srv.conf"
    SCRIPT_NAME = "homelab-srv"
    DEFAULT_BACKUP_FOLDER = "/srv/data/server-backup"
    SRV = Path("/srv")
    PERSIST = SRV / "persist"
    SRV_RUN = SRV / "run"
    CONFIG_YML = "_config.yml"
    SPECIAL_DOCKER_COMPOSE_NAME = ["syncthing"]

    def __repr__(self):
        return self.hostname

    @runez.cached_property
    def bcfg(self):
        return SrvFolder()

    @runez.cached_property
    def hostname(self):
        cmd = "/bin/hostname"
        return runez.run(cmd, dryrun=False, logger=None).output if os.path.exists(cmd) else os.environ.get("COMPUTERNAME") or ""

    @runez.cached_property
    def running_docker_images(self):
        r = run_docker("ps", logger=None)
        info = runez.parsed_tabular(r.output.strip().replace("CONTAINER ID", "CONTAINER_ID"))
        return {x["IMAGE"]: x["STATUS"] for x in info}

    @runez.cached_property
    def is_executor(self):
        """True if this host is supposed to run docker services"""
        return self.bcfg.folder and self.bcfg.folder is C.SRV_RUN

    @property
    def is_orchestrator(self):
        """True if this host is NOT supposed to run docker services, but remotely manage other servers instead"""
        return not self.is_executor

    def require_orchestrator(self):
        if not self.is_orchestrator:
            runez.abort("This command can only be ran from orchestrator machine")


GSRV = C()


def read_yml(path: Path, default=None):
    if path and path.exists():
        with open(path) as fh:
            return yaml.load(fh, Loader=yaml.BaseLoader)

    return default


def run_docker(*args, logger=logging.info):
    assert GSRV.is_executor
    return runez.run("docker", *args, logger=logger)


def slash_trail(path, trail=False):
    path = str(path).rstrip("/")
    return "%s/" % path if trail else path


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
    src = slash_trail(src, trail=need_trail)
    dest = slash_trail(dest, trail=need_trail)
    runez.run(*cmd, src, dest, logger=logging.info)


class DCItem:
    """Common things across docker-compose definitions we're working with"""

    def __init__(self, parent: Union["SrvFolder", "DCItem"], cfg=None, key=None):
        self.parent = parent
        self.yaml_key = key or self.__class__.__name__[2:].lower()
        self.cfg = cfg if cfg is not None else parent.cfg.get(self.yaml_key, {})  # type: dict

    def __repr__(self):
        return self.yaml_source

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
    def dc_config(self) -> "SrvFolder":
        return self._parent_of_type(SrvFolder)

    @runez.cached_property
    def yaml_source(self):
        keys = [self.yaml_key]
        parent = getattr(self, "parent")
        root = ""
        while parent:
            if isinstance(parent, SYDC):
                root = "%s:" % parent.dc_name
                break

            key = getattr(parent, "yaml_key", None)
            parent = getattr(parent, "parent", None)
            if key:
                keys.append(key)

        return root + "/".join(reversed(keys))


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
        expected_parts = (C.PERSIST / self.dc_file.dc_name).parts
        part_count = len(expected_parts)
        for vol in self.volumes:
            vol_parts = Path(vol).parts
            if len(vol_parts) >= part_count and vol_parts[:part_count] == expected_parts:
                n += 1

        return n == len(self.volumes)

    def sanity_check(self):
        if not self.cfg or self.dc_file.is_special:
            return

        expected_persist = C.PERSIST / self.dc_file.dc_name
        expected_parts = expected_persist.parts
        part_count = len(expected_parts)
        for vol in self.volumes:
            vol_parts = Path(vol).parts
            if len(vol_parts) < part_count or vol_parts[:part_count] != expected_parts:
                yield self, "Volume '%s' should be '%s'" % (vol, expected_persist.as_posix())


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
        yield from self.volumes.sanity_check()


class SYRun(DCItem):
    """'run:' entry in _config.yml"""

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
            yield self, "no hosts are defined in %s run: section" % C.CONFIG_YML

        for hostname, dc_names in self.dcs_by_host.items():
            yield from self.dc_config.dc_name_check(dc_names, "%s:run/%s" % (C.CONFIG_YML, hostname))


class SYBackup(DCItem):
    """'backup:' entry in _config.yml"""

    def __init__(self, parent):
        super().__init__(parent)
        self.folder = self.cfg.get("folder", C.DEFAULT_BACKUP_FOLDER)
        self.per_host = runez.flattened(self.cfg.get("per_host"), keep_empty=None, split=" ")
        self.restrict = self.cfg.get("restrict", {})

    def backup_destination(self, dc: "SYDC"):
        dest = Path(self.folder)
        if dc.dc_name in self.per_host:
            dest = dest / GSRV.hostname

        return dest / dc.dc_name

    def sanity_check(self):
        yield from self.dc_config.dc_name_check(self.per_host, "%s:backup/per_host" % C.CONFIG_YML)
        yield from self.dc_config.dc_name_check(self.restrict, "%s:backup/restrict" % C.CONFIG_YML)


class SYDC(DCItem):
    """Info from one docker-compose.yml file"""

    def __init__(self, parent, dc_path: Path):
        self.parent = parent
        self.dc_path = dc_path
        self.dc_name = dc_path.parent.name if dc_path.name == "docker-compose.yml" else dc_path.stem
        self.is_special = self.dc_name in C.SPECIAL_DOCKER_COMPOSE_NAME
        cfg = read_yml(dc_path) or {}
        super().__init__(parent, cfg=cfg.get("services", {}), key=self.dc_name)
        self.services = {}
        for k, v in self.cfg.items():
            service = DCService(self, k, v)
            self.services[service.service_name] = service

    def sanity_check(self):
        for s in self.services.values():
            yield from s.sanity_check()

    def run_docker_compose(self, *args):
        runez.run("docker-compose", "-f", self.dc_path, *args, stdout=None, stderr=None, logger=logging.info)

    @property
    def is_running(self):
        for image in self.images:
            status = GSRV.running_docker_images.get(image)
            if status:
                return status

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
                logging.info("Not %s '%s': special container" % (action, self.dc_name))

            return

        if not self.vanilla_backup:
            if not auto:
                logging.info("Not %s '%s': it does NOT use volume %s/%s" % (action, self.dc_name, C.PERSIST, self.dc_name))

            return

        configured = self.parent.backup.restrict.get(self.dc_name)
        configured = runez.flattened(configured, keep_empty=None, split=" ")
        if not configured:
            configured = [""]

        backup_dest = self.parent.backup.backup_destination(self)
        env = self.dc_config.env
        for rel_path in configured:
            src = C.PERSIST / self.dc_name / rel_path
            if runez.DRYRUN or src.is_dir():
                dest = backup_dest / rel_path
                if invert:
                    env = None
                    src, dest = dest, src

                if not auto or not dest.exists():
                    runez.ensure_folder(dest)
                    run_rsync(src, dest, sudo=True, env=env)

    def pull_images(self):
        """Using docker pull, apparently no way to see if docker-compose pull got a new image or not..."""
        updated = 0
        for image in self.images:
            r = run_docker("pull", image)
            if runez.DRYRUN or "newer image" in r.full_output:
                updated += 1

        return updated

    def restore(self, auto=False):
        self.backup(invert=True, auto=auto)

    def restart(self):
        assert GSRV.is_executor
        self.run_docker_compose("restart")

    def start(self):
        assert GSRV.is_executor
        self.run_docker_compose("start")

    def stop(self):
        assert GSRV.is_executor
        self.run_docker_compose("stop")
        self.backup()

    def upgrade(self, force=False):
        assert GSRV.is_executor
        updated = self.pull_images()
        if not force and not updated:  # pragma: no cover
            print("No new docker image available for %s" % self.dc_name)
            return

        self.run_docker_compose("down")
        self.backup()
        run_docker("image", "prune", "-f")
        self.run_docker_compose("up", "-d")


def find_base_folder() -> (Path, str):
    if not runez.log.current_test():  # pragma: no cover
        if C.SRV_RUN.is_dir():
            return C.SRV_RUN, None

        configured = runez.readlines(C.CONFIG_PATH, default=None, first=1)
        if configured and configured[0]:
            path = os.path.expanduser(configured[0])
            if path.endswith(C.CONFIG_YML):
                path = os.path.dirname(path)

            if os.path.isdir(path):
                return Path(path), C.CONFIG_PATH

            else:
                logging.warning("Path configured in %s is invalid: %s" % (C.CONFIG_YML, path))

    local = Path(os.getcwd()) / C.CONFIG_YML
    if local.exists():
        logging.info("Using %s from current working dir: %s" % (C.CONFIG_YML, local))
        return local.parent, "cwd"

    return None, None


class SrvFolder:
    """Config as defined by {folder}/_config.yml"""

    def __init__(self, folder=None):
        self.folder_origin = None
        if not folder:
            folder, self.folder_origin = find_base_folder()

        if folder and not isinstance(folder, Path):
            folder = Path(folder)

        self.folder = folder
        self.cfg_yml = self.folder and (self.folder / C.CONFIG_YML)
        self.cfg = read_yml(self.cfg_yml) or {}
        self.dc_files = {}  # type: dict[str, SYDC]

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
        return self.folder.as_posix() if self.folder else self.__class__.__name__

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
            yield self, "Run this to configure where your %s is: %s set-folder PATH" % (C.CONFIG_YML, C.SCRIPT_NAME)
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
