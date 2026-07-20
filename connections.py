"""Connection registry + auth injection — SHIPPED BY THE PLATFORM. DO NOT MODIFY.

Resolves same-origin /api/<slug>/... requests to an upstream base URL + auth.
The built-in 'tip' connection is always present (from TIP_API_URL / TIP_API_TOKEN).
Additional connections are read from a baked connections.json (written at deploy);
each names an env var holding its secret — secrets are never stored in the JSON.
"""
import base64
import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = BASE_DIR / "connections.json"


def host_is_safe(host: str) -> bool:
    """True only if every address `host` resolves to is a public one.

    Redirect targets are re-checked with this so a compromised upstream cannot
    302 the proxy toward internal / loopback / cloud-metadata addresses (SSRF).
    """
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def url_is_safe(url: str) -> bool:
    """http/https URL whose host resolves only to public addresses."""
    p = urlparse(url)
    return p.scheme in ("http", "https") and host_is_safe(p.hostname or "")


def load_connections() -> dict:
    """slug -> {base_url, auth_type, auth_location, secret_env}. Built-in 'tip' always included."""
    conns: dict = {}
    if _CONFIG_PATH.exists():
        try:
            raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                conns.update({str(k): v for k, v in raw.items() if isinstance(v, dict)})
        except (OSError, ValueError):
            pass  # a malformed config must never take down the proxy
    # Built-in TIP connection — always present, cannot be overridden by connections.json.
    conns["tip"] = {
        "base_url": os.getenv("TIP_API_URL", ""),
        "auth_type": "header",
        "auth_location": "x-api-key",
        "secret_env": "TIP_API_TOKEN",
    }
    return conns


def resolve_secret(conn: dict) -> str:
    return os.getenv(conn.get("secret_env", ""), "")


def inject_auth(conn: dict, headers: dict, params: dict, secret: str) -> None:
    """Mutate headers/params in place to attach the connection's auth (per auth_type)."""
    atype = (conn.get("auth_type") or "none").lower()
    loc = conn.get("auth_location") or ""
    if atype == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif atype == "header":
        if loc:
            headers[loc] = secret
    elif atype == "query_param":
        if loc:
            params[loc] = secret
    elif atype == "basic":
        token = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    # "none" or any unknown scheme → attach nothing
