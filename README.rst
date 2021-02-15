Manage /srv dockerized services
===============================

This CLI allows to manage a simple fleet of dockerized services at home.

It is based on a simple layout:

- There is a ``srv.yml`` file that describes what to run on what host.
- Services are all via one docker-compose file each, called ``<name>.yml``
- All services are configured to use ``/srv/persist/<name>`` as ``volumes:``
- Syncthing is assumed
