"""Run the server: ``python -m livematch [--host 127.0.0.1] [--port 8000]``."""

from __future__ import annotations

import argparse
import os


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Live match tracking server")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    print(f"Live Match Tracking -> http://{args.host}:{args.port}")
    uvicorn.run("livematch.api:app_factory", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
