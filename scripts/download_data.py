"""Download the public Metrica Sports sample data into data/raw/metrica.

Usage:
    python scripts/download_data.py

Uses ``git clone --depth 1`` (about 230 MB). Safe to re-run: skips if present.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/metrica-sports/sample-data.git"
ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "raw" / "metrica"


def main() -> int:
    games = TARGET / "data"
    if (games / "Sample_Game_1").exists() and (games / "Sample_Game_2").exists():
        print(f"Data already present in {TARGET}")
        return 0
    if shutil.which("git") is None:
        print("git is required to download the data", file=sys.stderr)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        shutil.rmtree(TARGET)
    print(f"Cloning {REPO_URL} -> {TARGET} ...")
    result = subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(TARGET)], check=False)
    if result.returncode != 0:
        print(
            "Download failed: the app still works with the bundled sample and the synthetic match.",
            file=sys.stderr,
        )
        return result.returncode
    print("Done. Available games:", ", ".join(sorted(p.name for p in games.iterdir())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
