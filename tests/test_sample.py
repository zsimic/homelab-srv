import os

import pytest
import runez

from homelab_srv import GlobalState, HomelabSite, slash_trail
from homelab_srv.cli import find_base_folder


def test_edge_cases(temp_folder, logged):
    assert str(GlobalState())
    assert find_base_folder(".", "foo") == (None, None, "foo")

    runez.touch("_sites.yml")
    assert find_base_folder(".", "foo") == (None, None, "foo")
    assert "is not valid yaml" in logged.pop()

    runez.write("_sites.yml", "foo: bar")
    assert find_base_folder(".", "foo") == (None, None, "foo")
    assert "does not define any 'sites:'" in logged.pop()

    runez.write("_sites.yml", "sites:\n  - site1")
    _, origin, _ = find_base_folder(".", "foo")
    assert "Site 'foo' is not defined" in logged.pop()
    assert origin == "cwd"


def from_sample(name, site=None):
    path = runez.log.tests_path(name)
    if site:
        path = os.path.join(path, site)

    return HomelabSite(path, site)


def test_sample():
    no_folder = HomelabSite(None)
    assert "Run this to configure" in str(list(no_folder.sanity_check()))

    no_folder = from_sample("no-such-folder")
    assert not no_folder.cfg
    assert not no_folder.dc_files
    assert "does not exist" in str(list(no_folder.sanity_check()))

    bogus = from_sample("bogus", "site1")
    problems = str(list(bogus.sanity_check()))
    assert "has no docker-compose files" in problems
    assert "referred from _site.yml:run/rps" in problems
    assert "referred from _site.yml:backup/per_host" in problems

    empty = from_sample("empty")
    problems = list(empty.sanity_check())
    assert "has no docker-compose files" in str(problems)
    assert "no hosts" in str(problems)

    cfg = from_sample("sample", "site1")
    assert str(cfg)
    assert cfg.get_hosts() == ["rps", "rph"]
    assert cfg.get_hosts("rps,rph") == ["rps", "rph"]
    assert len(cfg.get_dcs()) == 3
    assert len(cfg.get_dcs("all")) == 4
    assert len(cfg.get_dcs("special")) == 1
    assert len(cfg.get_dcs("vanilla")) == 2

    pihole = cfg.dc_files.get("pihole")
    assert pihole.images == ["pihole/pihole:latest"]
    with runez.CaptureOutput(dryrun=True):
        assert not pihole.is_running
        pihole.running_docker_images["pihole/pihole:latest"] = True
        assert pihole.is_running

    with pytest.raises(BaseException):
        cfg.get_hosts("foo")

    with pytest.raises(BaseException):
        cfg.get_dcs("foo")

    assert cfg.env == {"PGID": "1001", "PUID": "1001", "TZ": "America/Los_Angeles"}
    assert cfg.run.hostnames == ["rps", "rph"]


def test_slash_trail():
    assert slash_trail("foo") == "foo"
    assert slash_trail("foo/") == "foo"
    assert slash_trail("foo//") == "foo"
    assert slash_trail("foo", trail=True) == "foo/"
    assert slash_trail("foo/", trail=True) == "foo/"
    assert slash_trail("foo//", trail=True) == "foo/"
