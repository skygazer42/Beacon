import ipaddress

from django.core.management.base import BaseCommand, CommandError
from framework.wsgi import application
from waitress import serve


_ALLOWED_PROXY_HEADERS = {
    "forwarded",
    "x-forwarded-by",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
}


def _parse_proxy_headers(raw):
    headers = {
        item.strip().lower()
        for item in str(raw or "").split(",")
        if item.strip()
    }
    invalid = headers - _ALLOWED_PROXY_HEADERS
    if invalid:
        raise CommandError(
            "unsupported trusted proxy headers: %s" % ", ".join(sorted(invalid))
        )
    return headers


class Command(BaseCommand):
    help = "Serve Beacon Admin with the production Waitress WSGI server."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=9991)
        parser.add_argument("--threads", type=int, default=4)
        parser.add_argument("--trusted-proxy", default="")
        parser.add_argument(
            "--trusted-proxy-headers",
            default="x-forwarded-proto",
        )

    def handle(self, *args, **options):
        host = str(options.get("host") or "0.0.0.0").strip()
        port = int(options.get("port") or 0)
        threads = int(options.get("threads") or 0)
        trusted_proxy = str(options.get("trusted_proxy") or "").strip()

        if not host:
            raise CommandError("host must not be empty")
        if not 1 <= port <= 65535:
            raise CommandError("port must be between 1 and 65535")
        if not 1 <= threads <= 64:
            raise CommandError("threads must be between 1 and 64")

        serve_options = {
            "host": host,
            "port": port,
            "threads": threads,
            "ident": "Beacon",
            "expose_tracebacks": False,
        }
        if trusted_proxy:
            if trusted_proxy == "*":
                raise CommandError("wildcard trusted proxy is not allowed")
            try:
                ipaddress.ip_address(trusted_proxy)
            except ValueError as exc:
                raise CommandError("trusted proxy must be a single IP address") from exc
            headers = _parse_proxy_headers(options.get("trusted_proxy_headers"))
            if not headers:
                raise CommandError("trusted proxy headers must not be empty")
            serve_options.update(
                {
                    "trusted_proxy": trusted_proxy,
                    "trusted_proxy_count": 1,
                    "trusted_proxy_headers": headers,
                    "clear_untrusted_proxy_headers": True,
                }
            )

        self.stdout.write(
            "Starting Beacon Admin WSGI server on %s:%s with %s threads"
            % (host, port, threads)
        )
        serve(application, **serve_options)
