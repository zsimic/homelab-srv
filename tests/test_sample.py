import pytest
import runez

from homelab_srv import GSRV, SrvFolder


def test_sanity_check(cli):
    cli.expect_success("--version")
    assert cli.succeeded
    assert "homelab-srv" in cli.logged


def test_runs(cli):
    assert str(GSRV) == GSRV.hostname

    with runez.CurrentFolder(runez.log.tests_path("bogus")):
        cli.expect_failure("mkpass foo", "Please fix reported issues first")

    # Reset global state (applies to tests only...)
    del GSRV.bcfg

    with runez.CurrentFolder(runez.log.tests_path("sample")):
        cli.run("--dryrun", "set-folder", " ")
        assert cli.failed

        cli.expect_failure("--dryrun set-folder foo", "does not exist")  # No folder
        cli.expect_failure("--dryrun set-folder ..", "does not exist")  # No srv.yml
        cli.expect_success("--dryrun set-folder .", "Would write")

        if not runez.WINDOWS:
            cli.expect_success("mkpass foo")

        cli.expect_failure("--dryrun -se:rps set-folder foo", "can only be ran from orchestrator")

        cli.expect_success("-se:rps status", "executor")
        assert "syncthing" not in cli.logged

        cli.expect_success("-se:rps status all", "executor")
        assert "syncthing" in cli.logged

        cli.expect_success("-so:rps status", "orchestrator")

        cli.expect_failure("-se:rph stop rps:home-assistant", "Target host on executor must be self")
        cli.expect_success("-se:rph stop home-assistant", "not configured to run")

        cli.expect_success("-se:rps stop syncthing", "docker-compose... stop")
        cli.expect_success("-se:rps start syncthing", "docker-compose... up -d")
        cli.expect_success("-se:rps upgrade syncthing", "docker-compose... up -d")

        cli.expect_success("-so:rps backup", "ssh rps homelab-srv backup")
        cli.expect_success("-se:rps backup", "chown=1001")
        cli.expect_success("-se:rph backup pihole", "persist/pihole .../server-backup/rph/pihole", "Port 443 would conflict")
        cli.expect_success("-se:rps restore", "Would run", "Not restoring")
        cli.expect_success("-se:rps backup syncthing", "Not backing up 'syncthing': it does NOT use volume")

        cli.expect_success("--dryrun -so: push", "Would run:...rsync")


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
    assert "referred from srv.yml:run/rps" in problems
    assert "referred from srv.yml:backup/per_host" in problems

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
    with pytest.raises(BaseException):
        cfg.get_hosts("foo")

    with pytest.raises(BaseException):
        cfg.get_dcs("foo")

    assert cfg.env == {"PGID": "1001", "PUID": "1001", "TZ": "America/Los_Angeles"}
    assert cfg.run.hostnames == ["rps", "rph"]
