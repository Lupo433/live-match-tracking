"""Standalone fake live tracking provider (WebSocket on ws://HOST:PORT/feed).

Streams a recorded match at real time in a provider-specific format (see
``livematch.live.provider``), optionally with delay, loss, re-ordering and
periodic disconnections.

Usage:
    python scripts/fake_provider.py --match metrica_game_1 --port 8765 \
        --drop 0.01 --reorder 0.03 --delay-ms 150 --disconnect-every 90
"""

from __future__ import annotations

import argparse

import uvicorn

from livematch.catalog import default_catalog
from livematch.live.provider import FakeProvider, Impairments


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--match", default=None, help="match id (default: best available)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--start-minute", type=float, default=0.0)
    parser.add_argument("--delay-ms", type=float, default=0.0)
    parser.add_argument("--drop", type=float, default=0.0)
    parser.add_argument("--reorder", type=float, default=0.0)
    parser.add_argument("--disconnect-every", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    catalog = default_catalog()
    match_id = args.match or catalog.default_id
    source = catalog.get(match_id)
    provider = FakeProvider(
        source,
        speed=args.speed,
        start_frame=int(args.start_minute * 60 * source.info.fps),
        impairments=Impairments(
            delay_ms=args.delay_ms,
            drop_prob=args.drop,
            reorder_prob=args.reorder,
            disconnect_every_s=args.disconnect_every,
            seed=args.seed,
        ),
    )
    print(f"Streaming {match_id} on ws://{args.host}:{args.port}/feed")
    uvicorn.run(provider.app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
