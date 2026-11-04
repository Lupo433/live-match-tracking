"""Build the small committed sample in data/sample/ from the raw Metrica files.

Keeps the first ``--first`` seconds of the first half and the first ``--second``
seconds of the second half of Sample_Game_1 (same CSV format, header lines
preserved) plus the events that fall inside those windows. The defaults
(95 s + 25 s = 2 minutes) include the first goal (01:31) and the change of side.

Usage:
    python scripts/make_sample.py [--first 95] [--second 25]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "metrica" / "data" / "Sample_Game_1"
OUT = ROOT / "data" / "sample" / "Sample_Game_1"


def _crop_tracking(src: Path, dst: Path, limits: dict[str, float]) -> set[int]:
    kept: set[int] = set()
    per_period: dict[str, int] = {}
    with src.open(newline="") as fin, dst.open("w", newline="") as fout:
        reader, writer = csv.reader(fin), csv.writer(fout, lineterminator="\n")
        for _ in range(3):
            writer.writerow(next(reader))
        for row in reader:
            period = row[0]
            count = per_period.get(period, 0)
            if count < int(limits.get(period, 0) * 25):
                writer.writerow(row)
                kept.add(int(row[1]))
                per_period[period] = count + 1
    return kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=float, default=95.0)
    parser.add_argument("--second", type=float, default=25.0)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    kept: set[int] = set()
    for side in ("Home", "Away"):
        name = f"Sample_Game_1_RawTrackingData_{side}_Team.csv"
        kept = _crop_tracking(RAW / name, OUT / name, {"1": args.first, "2": args.second})
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
