"""Referral redirect service: hypha.link/b?u=<target>&t=<token>&v=<venue>
Logs the click then 302s to the (allow-listed) target. Run:
  uvicorn hypha.web.redirect:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlparse

import structlog
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, RedirectResponse

from ..db.models import Click
from ..db.session import init_models, session

log = structlog.get_logger(__name__)

# Open-redirect guard: only ever bounce to known buy venues.
ALLOWED_HOSTS = {
    "app.ston.fi", "swap.coffee", "www.swap.coffee",
    "gaspump.tg", "t.me", "dedust.io", "app.dedust.io",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_models()
    except Exception as exc:  # noqa: BLE001
        log.warning("db_init_failed", error=str(exc))
    yield


app = FastAPI(title="Hypha redirect", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


async def _log_click(token: str, venue: str, target: str) -> None:
    sess = session()
    if sess is None:
        log.info("click", token=token, venue=venue)  # DB-less: still observable in logs
        return
    async with sess as s:
        s.add(Click(token=token, venue=venue, target=target))
        await s.commit()


@app.get("/b")
async def buy(
    u: str = Query(..., description="target URL"),
    t: str = Query("", description="token address"),
    v: str = Query("", description="venue"),
):
    host = (urlparse(u).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"error": "blocked redirect target"}, status_code=400)
    try:
        await _log_click(t, v, u)
    except Exception as exc:  # noqa: BLE001 — never block the redirect on logging
        log.warning("click_log_failed", error=str(exc))
    return RedirectResponse(u, status_code=302)
