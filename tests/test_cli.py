import runez

from homelab_srv import GSRV


def test_sanity_check(cli):
    cli.expect_success("--version")
    assert cli.succeeded
    assert "homelab-srv" in cli.logged


def test_runs(cli):
    with runez.CurrentFolder(runez.log.tests_path("bogus")):
        cli.expect_failure(
            "start foo",
            "has no docker-compose files",
            "'home-assistant' does not exist",
            "'pihole' does not exist",
            "Please fix reported issues first",
        )

    # Reset global state (applies to tests only...)
    del GSRV.bcfg

    with runez.CurrentFolder(runez.log.tests_path("sample")):
        cli.expect_success("--dryrun meta set-folder", "No folder is currently configured")

        cli.expect_failure("--dryrun meta set-folder foo", "does not exist")  # No folder
        cli.expect_failure("--dryrun meta set-folder ..", "does not exist")  # No _config.yml
        cli.expect_success("--dryrun meta set-folder .", "Would write")

        if not runez.WINDOWS:
            cli.expect_success("meta mkpass foo")

        cli.expect_failure("--dryrun -se:rps meta set-folder foo", "can only be ran from orchestrator")

        cli.expect_success("meta ports", "443 ... pihole unifi-controller")
        cli.expect_success("meta ports -s", "syncthing ... 8384 21027 22000")

        cli.expect_success("-se:rps meta status", "executor")
        assert "syncthing" not in cli.logged

        cli.expect_success("-se:rps meta status all", "executor")
        assert "syncthing" in cli.logged

        cli.expect_success("-so:rps meta status", "orchestrator")

        cli.expect_failure("-se:rph stop rps:home-assistant", "Target host on executor must be self")
        cli.expect_success("-se:rph stop home-assistant", "not configured to run")

        cli.expect_success("-se:rps stop syncthing", "docker-compose... stop")
        cli.expect_success("-se:rps start syncthing", "docker-compose... up -d")
        cli.expect_success("-se:rps upgrade syncthing", "docker-compose... up -d")

        cli.expect_success("-so:rps backup", "ssh rps homelab-srv backup")
        cli.expect_success("-se:rps backup", "chown=1001")
        cli.expect_success("-se:rph backup pihole", "persist/pihole .../server-backup/rph/pihole", "Port 443 would conflict")
        cli.expect_success("-se:rps restore", "Would run", "Not restoring")
        cli.expect_success("-se:rps backup syncthing", "Not backing up 'syncthing': special container")

        cli.expect_success("--dryrun -so: push", "Would run:...rsync")
