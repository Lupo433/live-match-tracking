"""FastAPI application: REST endpoints + the live WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from livematch.catalog import Catalog, default_catalog
from livematch.session import (
    CheckpointStore,
    EngineFactory,
    MatchSession,
    event_dict,
    player_dict,
)

log = logging.getLogger("livematch")
WEB_DIR = Path(__file__).resolve().parent / "web"
TICK_S = 0.04  # 25 messages per second


def _default_engine_factory() -> EngineFactory | None:
    try:
        from livematch.metrics.engine import MetricsEngine
    except ImportError:  # pragma: no cover - metrics package not available
        return None
    return MetricsEngine.for_source


def create_app(
    catalog: Catalog | None = None,
    engine_factory: EngineFactory | None = None,
    tick_s: float = TICK_S,
    precompute: bool = True,
) -> FastAPI:
    """Build the application (dependencies injectable for tests).

    With ``precompute`` the metrics of each match are pre-computed once in a
    background thread (checkpoints every minute) so that seeking is instant.
    """
    catalog = catalog or default_catalog()
    engine_factory = engine_factory or _default_engine_factory()
    app = FastAPI(title="Live Match Tracking", version="0.1.0")
    app.state.catalog = catalog
    summary_cache: dict[str, dict[str, Any]] = {}
    stores: dict[str, CheckpointStore] = {}

    def _store(match_id: str) -> CheckpointStore | None:
        if not precompute or engine_factory is None:
            return None
        if catalog.get(match_id).info.source == "live":
            return None  # a growing source cannot be pre-computed
        if match_id not in stores:
            stores[match_id] = CheckpointStore(catalog.get(match_id), engine_factory).start()
        return stores[match_id]

    def _get_source(match_id: str):
        if match_id not in catalog:
            raise HTTPException(404, f"unknown match {match_id!r}")
        return catalog.get(match_id)

    def _matches() -> list[dict[str, Any]]:
        return [{"match_id": e.match_id, "title": e.title} for e in catalog.list()]

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/matches")
    def matches() -> dict[str, Any]:
        return {"default": catalog.default_id, "matches": _matches()}

    @app.get("/api/matches/{match_id}")
    def match_metadata(match_id: str) -> dict[str, Any]:
        src = _get_source(match_id)
        out: dict[str, Any] = {
            "match": src.info.to_dict(),
            "players": [player_dict(p) for p in src.players],
            "n_events": len(src.events),
        }
        status = getattr(src, "status", None)
        if callable(status):
            out["feed"] = status()  # live adapters: jitter-buffer / connection stats
        return out

    @app.get("/api/matches/{match_id}/events")
    def match_events(match_id: str) -> list[dict[str, Any]]:
        return [event_dict(e) for e in _get_source(match_id).events]

    @app.get("/api/matches/{match_id}/summary")
    def match_summary(match_id: str) -> dict[str, Any]:
        """Final statistics of the whole match (computed once, then cached)."""
        src = _get_source(match_id)
        if engine_factory is None:
            raise HTTPException(501, "metrics engine not available")
        store = stores.get(match_id)
        if store is not None and store.final_snapshot is not None:
            summary_cache[match_id] = store.final_snapshot
        if match_id not in summary_cache:
            engine = engine_factory(src)
            for frame in src.frames():
                engine.update(frame)
            summary_cache[match_id] = engine.snapshot()
        return {"match_id": match_id, "stats": summary_cache[match_id]}

    report_cache: dict[str, str] = {}

    @app.get("/api/matches/{match_id}/report", response_class=HTMLResponse)
    def match_report(match_id: str) -> HTMLResponse:
        """Self-contained post-match HTML report."""
        from livematch.metrics.engine import MetricsEngine
        from livematch.report import build_report, compute_final_engine

        src = _get_source(match_id)
        if match_id not in report_cache or src.info.source == "live":
            store = _store(match_id)  # background pre-computation (or disk cache)
            state = None
            if store is not None:
                deadline = time.monotonic() + 180
                while not store.done and time.monotonic() < deadline:
                    time.sleep(0.2)
                state = store.final_state()
            engine = compute_final_engine(src, state)
            assert isinstance(engine, MetricsEngine)
            report_cache[match_id] = build_report(src, engine)
        return HTMLResponse(report_cache[match_id])

    @app.get("/api/matches/{match_id}/passnetwork")
    def match_pass_network(
        match_id: str, until_frame: int | None = None, min_passes: int = 3
    ) -> dict[str, Any]:
        """Average positions and pass links of both teams (optionally up to a frame)."""
        from livematch.analytics.passes import pass_network
        from livematch.schema import Team

        src = _get_source(match_id)
        return {t.value: pass_network(src.events, t, until_frame) for t in (Team.HOME, Team.AWAY)}

    marketing_cache: dict[str, dict[str, Any]] = {}

    @app.get("/api/matches/{match_id}/marketing")
    def match_marketing(match_id: str) -> dict[str, Any]:
        """Excitement index per second + SYNTHETIC engagement, event study, correlation."""
        from livematch.engagement.marketing import marketing_payload

        src = _get_source(match_id)
        if src.info.source == "live":
            raise HTTPException(409, "marketing view needs a complete match")
        if match_id not in marketing_cache:
            store = _store(match_id)
            state = None
            if store is not None:
                deadline = time.monotonic() + 180
                while not store.done and time.monotonic() < deadline:
                    time.sleep(0.2)
                state = store.final_state()
            from livematch.report import compute_final_engine

            engine = compute_final_engine(src, state)
            marketing_cache[match_id] = marketing_payload(src, engine.excitement.series)
        return marketing_cache[match_id]

    @app.get("/api/models")
    def models_info() -> dict[str, Any]:
        """Metadata of the demonstrative xT / xG models."""
        from livematch.analytics.models import get_models

        m = get_models()
        xt = m.xt.to_dict()
        return {
            "meta": m.meta,
            "xg": m.xg.to_dict(),
            "xt": {k: v for k, v in xt.items() if k != "grid"} | {"grid": xt["grid"]},
        }

    @app.websocket("/ws")
    async def live(ws: WebSocket) -> None:
        await ws.accept()
        match_id = ws.query_params.get("match_id") or catalog.default_id
        if match_id not in catalog:
            match_id = catalog.default_id
        loop = asyncio.get_running_loop()

        async def new_session(mid: str) -> MatchSession:
            src = await loop.run_in_executor(None, catalog.get, mid)
            return MatchSession(src, engine_factory, store=_store(mid))

        await ws.send_json({"type": "loading", "match_id": match_id})
        session = await new_session(match_id)
        if ws.query_params.get("autoplay", "1") != "0":
            session.replay.play()
        await ws.send_json(session.init_message(_matches()))
        force_stats = True
        lock = asyncio.Lock()

        async def receiver() -> None:
            nonlocal session, force_stats
            while True:
                msg = await ws.receive_json()
                try:
                    if msg.get("cmd") == "select_match":
                        mid = str(msg.get("match_id"))
                        if mid not in catalog:
                            raise ValueError(f"unknown match {mid!r}")
                        await ws.send_json({"type": "loading", "match_id": mid})
                        new = await new_session(mid)
                        new.replay.play()
                        async with lock:
                            session = new
                        await ws.send_json(session.init_message(_matches()))
                    else:
                        async with lock:
                            session.handle(msg)
                    force_stats = True
                except (ValueError, KeyError, TypeError) as exc:
                    await ws.send_json({"type": "error", "message": str(exc)})

        async def sender() -> None:
            nonlocal force_stats
            next_t = time.perf_counter()
            while True:
                async with lock:
                    msg = session.tick(budget_s=tick_s * 0.6, force_stats=force_stats)
                force_stats = False
                await ws.send_json(msg)
                next_t += tick_s
                delay = next_t - time.perf_counter()
                if delay < -0.5:  # we fell far behind: re-sync instead of bursting
                    next_t = time.perf_counter()
                await asyncio.sleep(max(0.0, delay))

        tasks = [asyncio.create_task(receiver()), asyncio.create_task(sender())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    log.warning("websocket closed: %r", exc)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(BaseException):
                    await t

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory livematch.api:app_factory``."""
    return create_app()
