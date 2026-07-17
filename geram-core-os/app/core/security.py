"""Small request guards shared by sensitive local-only routes."""

from fastapi import HTTPException, Request, status


LOCALHOST_ADDRESSES = frozenset({"127.0.0.1", "::1"})


def require_localhost(request: Request) -> None:
    """Allow a request only when its direct socket peer is localhost."""
    client = request.scope.get("client")
    client_host = client[0] if client else None
    if client_host not in LOCALHOST_ADDRESSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is available from localhost only.",
        )


def require_local_origin(request: Request) -> None:
    """Validate a browser Origin while allowing non-browser local clients."""
    origin = request.headers.get("origin")
    if origin is None:
        return
    server = request.scope.get("server")
    server_port = server[1] if server else 8000
    allowed_origins = {
        f"http://localhost:{server_port}",
        f"http://127.0.0.1:{server_port}",
    }
    if origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This request origin is not allowed.",
        )
