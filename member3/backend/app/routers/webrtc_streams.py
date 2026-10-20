"""
AGHAT SETHU — WebRTC camera streams (WHEP proxy to MediaMTX)

    browser  --POST SDP offer + website JWT-->  /api/streams/{path}/whep
    backend  --POST SDP offer + reader basic auth-->  MediaMTX 127.0.0.1:8889/{path}/whep
    browser  <--SDP answer (201, Location: /api/streams/{path}/whep/{session})--
    browser  <==== SRTP media directly from MediaMTX (UDP 8189) ====>

Only signalling goes through the backend; video never does. MediaMTX's HTTP
listener is bound to loopback, so the website login (authority / admin, the
same rule as the Live page) is the only way to open a stream.

Endpoints (WHEP, draft-ietf-wish-whep):
    GET    /api/streams                          stream list + ICE servers
    POST   /api/streams/{path}/whep              offer -> answer (201 + Location)
    PATCH  /api/streams/{path}/whep/{session}    trickle ICE (sdpfrag)
    DELETE /api/streams/{path}/whep/{session}    end the session
"""

from __future__ import annotations

import json
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.config import settings
from app.dependencies.deps import require_authority
from app.models.models import User

router = APIRouter(prefix="/api/streams", tags=["WebRTC Streams"])

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_client: httpx.AsyncClient | None = None


def _streams() -> dict[str, str]:
    """path -> junction id, from WEBRTC_STREAMS ("J01:cam1,J02:cam2,...")."""
    out = {}
    for pair in settings.WEBRTC_STREAMS.split(","):
        if ":" in pair:
            junction, path = (part.strip() for part in pair.split(":", 1))
            if junction and re.fullmatch(r"[A-Za-z0-9_-]+", path):
                out[path] = junction
    return out


def _ice_servers() -> list[dict]:
    try:
        servers = json.loads(settings.WEBRTC_ICE_SERVERS)
        return servers if isinstance(servers, list) else []
    except ValueError:
        return []


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.MEDIAMTX_WHEP_URL.rstrip("/"),
            auth=(settings.MEDIAMTX_READ_USER, settings.MEDIAMTX_READ_PASS),
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
    return _client


def _check_path(path: str) -> None:
    if not settings.WEBRTC_ENABLED:
        raise HTTPException(status_code=503, detail="WebRTC streaming is disabled")
    if path not in _streams():
        raise HTTPException(status_code=404, detail=f"Unknown stream '{path}'")


async def _forward(method: str, url: str, body: bytes = b"", content_type: str | None = None,
                   extra_headers: dict | None = None) -> httpx.Response:
    headers = {**(extra_headers or {})}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        return await _http().request(method, url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502,
                            detail=f"Media server unreachable ({type(exc).__name__})") from exc


def _upstream_error(upstream: httpx.Response) -> HTTPException:
    if upstream.status_code == 404:          # nothing is publishing on that path yet
        return HTTPException(status_code=404, detail="Stream is offline (no publisher)")
    if upstream.status_code in (401, 403):   # backend reader credentials wrong
        return HTTPException(status_code=502, detail="Media server rejected the backend credentials")
    return HTTPException(status_code=502, detail=f"Media server error {upstream.status_code}: "
                                                 f"{upstream.text[:200]}")


@router.get("")
def list_streams(_: User = Depends(require_authority)):
    return {
        "enabled": settings.WEBRTC_ENABLED,
        "streams": [{"junction_id": junction, "path": path, "whep_url": f"/api/streams/{path}/whep"}
                    for path, junction in _streams().items()],
        "ice_servers": _ice_servers(),
    }


@router.post("/{path}/whep")
async def whep_offer(path: str, request: Request, _: User = Depends(require_authority)):
    _check_path(path)
    offer = await request.body()
    if not offer.startswith(b"v=0"):
        raise HTTPException(status_code=400, detail="Body must be an SDP offer (application/sdp)")
    upstream = await _forward("POST", f"/{path}/whep", offer, "application/sdp")
    if upstream.status_code != 201:
        raise _upstream_error(upstream)
    session = upstream.headers.get("location", "").rstrip("/").rsplit("/", 1)[-1]
    headers = {"Location": f"/api/streams/{path}/whep/{session}",
               "Cache-Control": "no-store"}
    for name in ("ETag", "Accept-Patch"):
        if name in upstream.headers:
            headers[name] = upstream.headers[name]
    return Response(content=upstream.content, status_code=201, media_type="application/sdp",
                    headers=headers)


@router.patch("/{path}/whep/{session}")
async def whep_trickle(path: str, session: str, request: Request, _: User = Depends(require_authority)):
    _check_path(path)
    if not SESSION_RE.fullmatch(session):
        raise HTTPException(status_code=400, detail="Bad session id")
    extra = {"If-Match": request.headers["if-match"]} if "if-match" in request.headers else None
    upstream = await _forward("PATCH", f"/{path}/whep/{session}", await request.body(),
                              request.headers.get("content-type", "application/trickle-ice-sdpfrag"), extra)
    if upstream.status_code not in (200, 204):
        raise _upstream_error(upstream)
    return Response(status_code=204)


@router.delete("/{path}/whep/{session}")
async def whep_delete(path: str, session: str, _: User = Depends(require_authority)):
    _check_path(path)
    if not SESSION_RE.fullmatch(session):
        raise HTTPException(status_code=400, detail="Bad session id")
    upstream = await _forward("DELETE", f"/{path}/whep/{session}")
    # 404: the session already ended (viewer left, server restarted) - same outcome
    if upstream.status_code not in (200, 204, 404):
        raise _upstream_error(upstream)
    return Response(status_code=204)


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
