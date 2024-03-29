import logging
import os
import time
from pathlib import Path

import runez

from homelab_srv import GSRV, run_rsync, run_uncaptured, SRV_SSL


def file_age(path):
    """Age (in days) of file with 'path'"""
    try:
        seconds = time.time() - os.path.getmtime(path)
        return seconds / runez.date.SECONDS_IN_ONE_DAY

    except Exception:
        return 100 if runez.DRYRUN else -1


class SslFiles:
    def __init__(self, folder, domain):
        self.domain = domain
        self.cert_file = folder

    def __repr__(self):
        return "SSL %s" % self.domain


class CertbotDomain:
    def __init__(self, runner, domain):
        self.runner = runner  # type: CertbotRunner
        self.domain = domain
        self.base = self.runner.folder / domain
        self.certbot_config = self.base / "config"
        self.deployed = self.runner.deployed / domain
        self.pems = ["cert.pem", "chain.pem", "fullchain.pem", "privkey.pem"]

    def source(self, name):
        return self.certbot_config / "live" / self.domain / name

    def dest(self, name):
        return self.deployed / name

    def run_certbot(self):
        self.runner.run_certbot(
            "--email=%s" % (self.runner.email or "certbot@%s" % self.domain),
            "--config-dir=%s" % self.certbot_config,
            "--logs-dir=%s" % (self.base / "logs"),
            "--work-dir=%s" % (self.base / "work"),
            "-d", "*.%s" % self.domain,
            "-d", self.domain,
        )

    def renew(self):
        age = file_age(self.deployed / "privkey.pem")
        if 0 <= age <= self.runner.days_cutoff:
            logging.info("Certs are still valid for %s: %.0f days old (out of %s)" % (self.domain, age, self.runner.days_cutoff))
            return

        self.run_certbot()
        for fname in self.pems:
            runez.copy(self.source(fname), self.dest(fname))

        if self.runner.is_staging:
            logging.info("Staging run: not publishing certs")
            return

        for target in self.runner.publish:
            if target:
                run_rsync(self.deployed, target.format(domain=self.domain))


class CertbotRunner:
    """
    /srv/ssl/
        deployed/domain1.com/*.pem
        domain1.com/
            config/live/domain1.com/*.pem
            logs/
            work/
        venv/
    """
    def __init__(self):
        self.cfg = GSRV.bcfg.cfg.get("certbot")
        if not self.cfg:
            runez.abort("There is no 'certbot' section in %s" % GSRV)

        self.host = self.get_value("host")
        provider = self.get_value("provider")
        self.provider, _, self.creds = provider.partition("@")
        if not self.creds:
            runez.abort("No %s credentials configured in %s:certbot/provider" % (provider, GSRV))

        self.creds = Path(self.creds).expanduser()
        if not runez.DRYRUN and not self.creds.exists():
            runez.abort("Credentials file '%s' does not exist in (configured in %s:certbot/provider)" % (self.creds, GSRV))

        self.folder = SRV_SSL
        if self.is_staging:
            self.folder = GSRV.bcfg.folder / "_ssl"

        self.deployed = self.folder / "deployed"
        self.venv = self.folder / "venv"
        self.venv_bin = self.venv / "bin"
        self.email = self.get_value("email", required=False)
        self.domains = runez.flattened(self.get_value("domains"))
        publish = self.get_value("publish", required=False)
        self.publish = runez.flattened(publish) if publish else []
        self.days_valid = 90
        self.days_prior = 20
        self.days_cutoff = self.days_valid - self.days_prior

    @runez.cached_property
    def is_staging(self):
        return not GSRV.is_executor or GSRV.hostname != self.host

    def get_value(self, key, required=True):
        v = self.cfg.get(key)
        if required and v is None:
            runez.abort("Missing key '%s' in %s:certbot" % (key, GSRV))

        return v

    def update_certs(self, domains=None):
        if not domains:
            domains = self.domains

        domains = runez.flattened(domains, split=",")
        for domain in domains:
            d = CertbotDomain(self, domain)
            d.renew()

    def run_certbot(self, *args):
        self.auto_install_certbot()
        run_uncaptured(
            self.venv_bin / "certbot",
            "certonly",
            "--staging" if self.is_staging else None,
            "--non-interactive",
            "--agree-tos",
            "--max-log-backups=5",
            "--preferred-challenges=dns",
            "--dns-%s" % self.provider,
            "--dns-%s-credentials=%s" % (self.provider, self.creds),
            *args,
        )

    def auto_install_certbot(self):
        age = file_age(self.venv)
        if 0 <= age <= 60:
            return

        runez.delete(self.venv)
        runez.run("virtualenv", self.venv)
        run_uncaptured(self.venv_bin / "pip", "install", "certbot", "certbot-dns-%s" % self.provider)
