"""Run the server.

``python -m livematch [--host 127.0.0.1] [--port 8000]``
``python -m livematch --live-demo`` also starts a fake live provider and
connects the app to it (match "live_demo").
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Live match tracking server")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    live = parser.add_argument_group("live demo")
    live.add_argument("--live-demo", action="store_true", help="start fake provider + adapter")
    live.add_argument("--provider-port", type=int, default=8765)
    live.add_argument("--start-minute", type=float, default=0.0)
    live.add_argument("--drop", type=float, default=0.01, help="tracking packet loss prob.")
    live.add_argument("--reorder", type=float, default=0.03, help="out-of-order prob.")
    live.add_argument("--delay-ms", type=float, default=150.0, help="network delay")
    live.add_argument("--disconnect-every", type=float, default=90.0, help="seconds, 0 = never")
    args = parser.parse_args()
    print(f"Live Match Tracking -> http://{args.host}:{args.port}")
    if not args.live_demo:
        uvicorn.run("livematch.api:app_factory", factory=True, host=args.host, port=args.port)
        return

    from livematch.api import create_app
    from livematch.live.demo import build_live_demo_catalog
    from livematch.live.provider import Impairments

    imp = Impairments(
        delay_ms=args.delay_ms,
        drop_prob=args.drop,
        reorder_prob=args.reorder,
        disconnect_every_s=args.disconnect_every,
    )
    catalog = build_live_demo_catalog(args.provider_port, imp, args.start_minute)
    uvicorn.run(create_app(catalog), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
