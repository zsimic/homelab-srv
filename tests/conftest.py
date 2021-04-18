from runez.conftest import cli, logged, temp_folder  # noqa: F401 (fixtures)

from homelab_srv.cli import main


cli.default_main = main
