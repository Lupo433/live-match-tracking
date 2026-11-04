"""Build the small committed sample in data/sample/ from the raw Metrica files.

Keeps the first SECONDS of each half of Sample_Game_1 (same CSV format,
header lines preserved) plus the events that fall inside those windows.

Usage:
    python scripts/make_sample.py [--seconds 60]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "metrica" / "data" / "Sample_Game_1"
OUT = ROOT / "data" / "sample" / "Sample_Game_1"


def _crop_tracking(src: Path, dst: Path, seconds: float) -> set[int]:
    kept: set[int] = set()
    per_period: dict[str, int] = {}
    limit = int(seconds * 25)
    with src.open(newline="") as fin, dst.open("w", newline="") as fout:
        reader, writer = csv.reader(fin), csv.writer(fout, lineterminator="\n")
        for _ in range(3):
            writer.writerow(next(reader))
        for row in reader:
            period = row[0]
            count = per_period.get(period, 0)
            if count < limit:
                writer.writerow(row)
                kept.add(int(row[1]))
                per_period[period] = count + 1
    return kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=60.0)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    kept: set[int] = set()
    for side in ("Home", "Away"):
        name = f"Sample_Game_1_RawTrackingData_{side}_Team.csv"
        kept = _crop_tracking(RAW / name, OUT / name, args.seconds)
    ev_name = "Sample_Game_1_RawEventsData.csv"
    with (RAW / ev_name).open(newline="") as fin, (OUT / ev_name).open("w", newline="") as fout:
        reader, writer = csv.reader(fin), csv.writer(fout, lineterminator="\n")
        writer.writerow(next(reader))
        for row in reader:
            if int(row[4]) in kept:
                writer.writerow(row)
    print(f"Sample written to {OUT} ({len(kept)} frames)")


if __name__ == "__main__":
    main()
