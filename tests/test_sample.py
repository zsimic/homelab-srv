import pytest
import runez

from homelab_srv import slash_trail, SrvFolder


def test_sample():
    no_folder = SrvFolder(None)
    assert "Run this to configure" in str(list(no_folder.sanity_check()))

    no_folder = SrvFolder(runez.log.tests_path("no-such-folder"))
    assert not no_folder.cfg
    assert not no_folder.dc_files
    assert "does not exist" in str(list(no_folder.sanity_check()))

    bogus = SrvFolder(runez.log.tests_path("bogus"))
    problems = str(list(bogus.sanity_check()))
    assert "has no docker-compose files" in problems
    assert "referred from _config.yml:run/rps" in problems
    assert "referred from _config.yml:backup/per_host" in problems

    empty = SrvFolder(runez.log.tests_path("empty"))
    problems = list(empty.sanity_check())
    assert "has no docker-compose files" in str(problems)
    assert "no hosts" in str(problems)

    folder = runez.log.tests_path("sample")
    cfg = SrvFolder(folder)
    assert str(cfg)
    assert cfg.get_hosts() == ["rps", "rph"]
    assert cfg.get_hosts("rps,rph") == ["rps", "rph"]
    assert len(cfg.get_dcs()) == 3
    assert len(cfg.get_dcs("all")) == 4
    assert len(cfg.get_dcs("special")) == 1
    assert len(cfg.get_dcs("vanilla")) == 2

    pihole = cfg.dc_files.get("pihole")
    assert pihole.images == ["pihole/pihole:latest"]

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
