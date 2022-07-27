Manage /srv dockerized services
===============================

This CLI allows to manage a simple fleet of dockerized services at home.

It is based on a simple layout:

- Services are defined via one docker-compose file each, called:
    - ``<name>.yml``
    - or ``<name>/docker-compose.yml``
- All services are configured to use ``/srv/persist/<name>`` as ``volumes:``


Installation
============

```
    pickley install https://github.com/zsimic/homelab-srv.git
```
