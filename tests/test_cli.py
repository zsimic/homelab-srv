import runez


def test_sanity_check(cli):
    cli.expect_success("--version")
    assert cli.succeeded
    assert "homelab-srv" in cli.logged


def test_bogus(cli):
    with runez.CurrentFolder(runez.DEV.tests_path("bogus")):
        cli.expect_failure(
            "start foo",
            "has no docker-compose files",
            "'home-assistant' does not exist",
            "'pihole' does not exist",
            "Please fix reported issues first",
        )


def test_certbot(cli):
    with runez.CurrentFolder(runez.DEV.tests_path("sample")):
        cli.run("-n certbot example.com")
        assert cli.succeeded
        assert "pip install certbot certbot-dns-linode" in cli.logged
        assert "--staging" in cli.logged
        assert "not publishing certs" in cli.logged

        cli.run("-n -s:rps certbot example.com")
        assert cli.succeeded
        assert "--staging" not in cli.logged
        assert "rsync" in cli.logged
        assert "some-remote-host:" in cli.logged


def test_sample(cli):
    with runez.CurrentFolder(runez.DEV.tests_path("sample")):
        cli.expect_success("-n meta set-folder", "No folder is currently configured")

        cli.expect_failure("-n meta set-folder foo", "does not exist")  # No folder
        cli.expect_failure("-n meta set-folder ..", "does not exist")  # No _config.yml
        cli.expect_success("-n meta set-folder .", "Would write")

        if not runez.WINDOWS:
            cli.expect_success("meta mkpass foo")

        cli.expect_failure("-n -s:rps meta set-folder foo", "can only be ran from orchestrator")

        cli.expect_success("-n -s:rps meta status", "executor")
        assert "syncthing" not in cli.logged

        cli.expect_success("-n -s:rps meta status all", "executor")
        assert "syncthing" in cli.logged

        cli.expect_success("meta status --ports", "orchestrator")

        cli.expect_failure("-n -s:rph stop rps:home-assistant", "Target host on executor must be self")
        cli.expect_success("-n -s:rph stop home-assistant", "not configured to run")

        cli.run("-n upgrade home-assistant")
        assert cli.succeeded
        assert "ssh rps homelab-srv" in cli.logged
        assert "rph" not in cli.logged

        cli.run("-n upgrade home-assistant --force")
        assert cli.succeeded
        assert "ssh rps homelab-srv upgrade home-assistant --force" in cli.logged

        cli.expect_success("-n ps", "Would run:...ssh ... --color ps")
        cli.expect_success("-n -s:rps ps", "not running")

        cli.expect_success("-n -s:rps stop syncthing", "docker-compose... down")
        cli.expect_success("-n -s:rps start syncthing", "docker-compose... start")
        cli.expect_success("-n -s:rps logs syncthing", "docker-compose... logs")
        cli.expect_success("-n -s:rps restart syncthing", "docker-compose... restart")
        cli.expect_success("-n -s:rps upgrade syncthing", "docker-compose... up -d")

        cli.expect_success("-n backup", "ssh rps homelab-srv backup")
        cli.expect_success("-n -s:rps backup", "chown=1001", "--exclude log")
        cli.expect_success("-n --debug -s:rps backup syncthing", "Not backing up 'syncthing': special container")

        cli.run("-n -s:rph backup pihole")
        assert cli.succeeded
        assert cli.match("rsync .+ --delete --chown=1001:1001 .srv.persist.pihole .srv.data.server-backup.rph.pihole", regex=True)
        assert cli.match("Port 443 would conflict")

        cli.run("-n -s:rph restore pihole")
        assert cli.succeeded
        assert cli.match("rsync .+ --delete .srv.data.server-backup.rph.pihole .srv.persist.pihole", regex=True)

        cli.run("-n --debug -s:rps restore")
        assert cli.succeeded
        assert "Not restoring" in cli.logged

        cli.run("-n --debug push -u foo")
        assert cli.failed
        assert "Host 'foo' is not defined in config" in cli.logged

        cli.expect_success("-n push", "Would run:...rsync")


def test_seed(cli):
    site = runez.DEV.tests_path("sample")
    cli.run("-n -ssite1@%s seed ssh --key my-key foo@bar" % site)
    assert cli.failed
    assert "does not exist" in cli.logged

    runez.touch("my-key")
    cli.run("-n -ssite1@%s seed ssh --key my-key foo@bar" % site)
    assert cli.succeeded
    assert "already works" in cli.logged
