"""API proxy — SHIPPED BY THE PLATFORM. DO NOT MODIFY OR RECREATE THIS FILE.

The browser calls same-origin /api/<slug>/<path> (or /tip-api/<path> for the
built-in TIP connection); this router resolves the connection, attaches its auth
server-side, forwards the request, and streams the upstream response back verbatim.
"""
from urllib.parse import urljoin, urlparse

import requests
from fastapi import APIRouter, Request, Response

from connections import inject_auth, load_connections, resolve_secret, url_is_safe

router = APIRouter()

# Hop-by-hop / recomputed headers we must not forward as-is. Dropping
# accept-encoding means the upstream returns an uncompressed body, so streaming
# bytes back with the upstream Content-Type is always consistent for the browser.
_DROP_HEADERS = {"host", "content-length", "connection", "accept-encoding"}
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


def _json_error(message: str, status: int) -> Response:
    return Response(
        content=('{"status": false, "message": "%s"}' % message).encode(),
        status_code=status, media_type="application/json",
    )


def _forward(slug: str, path: str, request: Request, body: bytes) -> Response:
    conn = load_connections().get(slug)
    if conn is None:
        return _json_error("unknown_connection", 404)

    base = (conn.get("base_url", "") or "").rstrip("/")
    origin_host = urlparse(base).hostname
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS}
    secret = resolve_secret(conn)

    method = request.method
    cur_url = f"{base}/{path.lstrip('/')}"
    cur_body = body
    cur_params = dict(request.query_params)

    # Follow redirects manually so every hop is re-checked against the SSRF gate and
    # the injected secret is only ever sent to the connection's OWN host.
    for _hop in range(_MAX_REDIRECTS + 1):
        headers = dict(fwd_headers)
        params = dict(cur_params)
        if urlparse(cur_url).hostname == origin_host:
            inject_auth(conn, headers, params, secret)
        try:
            upstream = requests.request(
                method=method, url=cur_url, params=params, data=cur_body,
                headers=headers, timeout=60, allow_redirects=False,
            )
        except requests.RequestException:
            return _json_error("proxy_error", 502)

        location = upstream.headers.get("Location")
        if upstream.status_code in _REDIRECT_CODES and location:
            target = urljoin(cur_url, location)
            if not url_is_safe(target):
                return _json_error("blocked_redirect", 502)
            if upstream.status_code in (301, 302, 303):
                method, cur_body = "GET", None  # 303 (and de-facto 301/302) drop the body
            cur_params = {}                      # the redirect Location carries its own query
            cur_url = target
            continue

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("Content-Type", "application/json"),
        )

    return _json_error("too_many_redirects", 502)


@router.api_route("/api/{slug}/{path:path}", methods=_METHODS)
async def api_proxy(slug: str, path: str, request: Request) -> Response:
    return _forward(slug, path, request, await request.body())


@router.api_route("/tip-api/{path:path}", methods=_METHODS)
async def tip_api_proxy(path: str, request: Request) -> Response:
    return _forward("tip", path, request, await request.body())
