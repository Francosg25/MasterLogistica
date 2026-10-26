"""Local identity is available only on loopback, never through a reverse proxy."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


def local_request_allowed(scope, origins):
    try:
        if not ip_address(scope.get("client", (None,))[0]).is_loopback:
            return False
    except (ValueError, TypeError):
        return False
    raw_headers = scope.get("headers", [])
    if any(sum(key.lower() == name for key, _ in raw_headers) > 1 for name in (b"host", b"origin")):
        return False
    headers = {key.lower(): value for key, value in raw_headers}
    if any(key == b"forwarded" or key.startswith(b"x-forwarded-") for key in headers):
        return False
    try:
        parsed = urlsplit("http://" + headers.get(b"host", b"").decode("latin-1"))
        host = parsed.hostname
        if parsed.username or parsed.path or parsed.query or parsed.fragment:
            return False
    except ValueError:
        return False
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return False
    origin = headers.get(b"origin")
    return origin is None or origin.decode("latin-1") in origins


class LocalAccessMiddleware:
    def __init__(self, app, origins):
        self.app = app
        self.origins = origins

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"} and not local_request_allowed(
            scope, self.origins
        ):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                response = JSONResponse(
                    {"detail": "El modo de desarrollo solo admite esta computadora, sin proxies."},
                    status_code=403,
                )
                await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
