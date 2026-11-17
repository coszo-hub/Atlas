#!/usr/bin/env python3
"""The cabled SCPR's in-situ calibrations, from its control log on the PI portal.

The SCPR (RS03CCAL-MJ03F-09-SCPRAA301) calibrates its two quartz gauges in place with a deadweight piston gauge that
is spun mechanically while a calibration runs (Sasagawa et al., 2022: "performed under operator supervision on a
regular basis ... reduced to monthly and then quarterly"). Its control log (SCPRAA301_SCPR, one line a second:
N UNIX_SEC LVDT1 LVDT2 BARO PRT RPM XTILT YTILT) shows the piston turning (RPM > 0) during each one. This reads the
daily files from the newest back and records each calibration's start and end, until it has found --want of them
or read --max-days days. Each day's file is ~8 MB, so this runs when the gold or the calibration record is rebuilt,
not for each question.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = "http://piweb.ooirsn.uw.edu/scpr/data/SCPRAA301_SCPR/"
OLD_BASE = "http://piweb.ooirsn.uw.edu/scpr/data/SCPR_Data/SCPRAA301_SCPR/"   # 2018-2022 (Sasagawa et al. 2022's calibrations)
LINE = re.compile(rb"<log-ts:(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)[^>]*>\s+(\S+)\s+(\d+)\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)\s")
GAP = 1800   # seconds without the piston turning that end one calibration


def get(url: str, timeout: int = 300) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "RCA-Atlas/1.0"}), timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


_LISTINGS: dict[str, list[bytes]] = {}


def day_file(day: date) -> str | None:
    for base in (BASE, OLD_BASE):
        folder = f"{base}{day:%Y/%m}/"
        if folder not in _LISTINGS:
            listing = get(folder, timeout=60) or b""
            _LISTINGS[folder] = re.findall(rb'href="([^"?/]+)"', listing)
        name = next((n.decode() for n in _LISTINGS[folder] if f"_{day:%Y%m%d}T".encode() in n), None)
        if name:
            return f"{folder}{name}"
    return None


def spinning(raw: bytes) -> list[str]:
    """The log times (to the second) when the piston was turning."""
    return [m.group(1).decode() for m in LINE.finditer(raw) if int(m.group(4)) > 0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--want", type=int, default=2, help="Calibrations to find, newest first.")
    parser.add_argument("--max-days", type=int, default=200)
    parser.add_argument("--start", help="Read back from this day (YYYY-MM-DD); default today.")
    args = parser.parse_args()
    today = date.fromisoformat(args.start) if args.start else datetime.now(timezone.utc).date()
    times, read, files = [], 0, []
    for back in range(args.max_days):
        day = today - timedelta(days=back)
        url = day_file(day)
        if not url:
            continue
        raw = get(url)
        read += 1
        if raw:
            t = spinning(raw)
            if t:
                times += t
                files.append(url)
        events = []
        for ts in sorted(set(times)):
            sec = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            if events and sec - events[-1]["_end"] <= GAP:
                events[-1]["_end"], events[-1]["end"] = sec, ts
            else:
                events.append({"start": ts, "end": ts, "_start": sec, "_end": sec})
        # A calibration seen whole: a newer day without spinning was read after it, or it ended long before midnight.
        if len(events) >= args.want and back > 0:
            break
    for e in events:
        e["minutes"] = round((e.pop("_end") - e.pop("_start")) / 60, 1)
    out = {"instrument": "RS03CCAL-MJ03F-09-SCPRAA301", "source": BASE, "method": "piston gauge turning (RPM > 0) in the control log",
           "read_days": read, "scanned_from": str(today), "scanned_back_to": str(today - timedelta(days=back)),
           "calibrations_newest_first": sorted(events, key=lambda e: e["start"], reverse=True), "files": files}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("read_days", "scanned_back_to")} | {"calibrations": out["calibrations_newest_first"][:4]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
