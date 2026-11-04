"""``python -m livematch --live-demo``: fake provider + app connected to it."""

from __future__ import annotations

import logging
import threading
import time

from livematch.catalog import Catalog, MatchEntry, default_catalog
from livematch.live.provider import FakeProvider, Impairments
from livematch.sources.live_stub import ProviderFeedSource

log = logging.getLogger("livematch.live")


def pick_recording(catalog: Catalog) -> str:
    for mid in ("metrica_game_1", "metrica_game_2", "sample_game_1", "synthetic"):
        if mid in catalog:
            return mid
    raise RuntimeError("no match available for the fake provider")


def start_provider(
    recording,
    port: int,
    impairments: Impairments,
    start_frame: int = 0,
) -> FakeProvider:
    """Run the fake provider in a background uvicorn server."""
    import uvicorn

    provider = FakeProvider(recording, start_frame=start_frame, impairments=impairments)
    config = uvicorn.Config(provider.app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="fake-provider").start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return provider


def live_entry(url: str, match_id: str = "live_demo") -> MatchEntry:
    def load() -> ProviderFeedSource:
        src = ProviderFeedSource(url, match_id=match_id, title="LIVE demo (fake provider)")
        src.connect()
        if not src.wait_ready(20.0):
            raise RuntimeError(f"no line-up received from {url}")
        return src

    return MatchEntry(match_id, "● LIVE demo (fake provider)", load)


def build_live_demo_catalog(
    provider_port: int = 8765,
    impairments: Impairments | None = None,
    start_minute: float = 0.0,
) -> Catalog:
    catalog = default_catalog()
    rec_id = pick_recording(catalog)
    recording = catalog.get(rec_id)
    imp = impairments or Impairments()
    start = int(start_minute * 60 * recording.info.fps)
    start_provider(recording, provider_port, imp, start_frame=start)
    log.warning("fake provider streaming %s on ws://127.0.0.1:%d/feed", rec_id, provider_port)
    catalog.add(live_entry(f"ws://127.0.0.1:{provider_port}/feed"), default=True)
    catalog.get("live_demo")  # connect now, so the live match starts at kick-off
    return catalog
