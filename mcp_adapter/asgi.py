"""Additive ASGI entrypoint for a separate deployment; existing server stays unchanged."""
import os
import re
from mcp.server.transport_security import TransportSecuritySettings
from .server import create_server


def create_app(backend=None, public_hosts=None):
    if public_hosts is None:
        public_hosts = [os.environ.get(key, "") for key in
                        ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "EVE_MCP_PUBLIC_HOST")]
    hosts = []
    for host in public_hosts:
        if not host:
            continue
        if len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            raise ValueError("MCP public hosts must be DNS hostnames without scheme, path or wildcard")
        hosts.append(host.lower())
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*"] + hosts,
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"] + ["https://" + host for host in hosts],
    )
    return create_server(backend).streamable_http_app(
        stateless_http=True, json_response=True, transport_security=security)


app = create_app()
