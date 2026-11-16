"""The Watcher's list: which sensors the daily check grades, how, and the longest gap that is normal for each.

Built from the map bundle (src/atlas_map/public/atlas/sensors.json) and Nereus, the RCA's instrument monitor, which
tracks the RS and the Endurance (CE) cabled instruments. A sensor is watched when it is in the water and meant to be
recording: an OOI instrument with a full reference designator whose Nereus operational status is operating, partially
functional, failed or offline (the last two show red, with Nereus's word for it), or, where Nereus has none, whose
map status is operating, partially functional or unknown; and the OO seismic stations EarthScope serves. Not
deployed, retired, superseded, uncabled and recovered instruments are not, nor planned ones, reference-only records
(no port number), or campaign and PI instruments (the pressure benchmarks, the DAS experiments, FETCH, DEMS, COVIS);
OVERRIDES adds or drops one by hand.

Each watched sensor is checked one way, the first that serves it:
  earthscope  an OO seismic station: its 8 Hz (MHZ) and 200 Hz (HHZ, EHZ) data at EarthScope; 8 Hz without 200 Hz
              is the Navy's diversion of the high-rate data. A low-frequency hydrophone: its 200 Hz channel (HDH) on
              the station it shares, against that station's 8 Hz
  nereus      Nereus's hourly data check (GOOD, BAD) over the day, else its file check for an instrument it checks
              only by its files
  erddap      OOI ERDDAP (the map's dataset, else ERDDAP's own for the designator): the 10-minute bins with data
  rawdata     a broadband hydrophone: its 5-minute files on OOI's raw data server
  none        nothing public says whether it recorded (QA/QC plots not updated since 2024); listed, not graded
A sensor with an ERDDAP dataset besides its Nereus check is checked by both (check.py takes the worse).
Usage: python build_watchlist.py [--sensors PATH] [--out PATH]"""
import argparse
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/nereus_pipeline"))

ERDDAP = "https://erddap.dataexplorer.oceanobservatories.org/erddap"
WATCHED_STATUS = {"OPERATIONAL", "PARTIALLY_FUNCTIONAL", "UNKNOWN"}
# Nereus's operational status, where it has one, decides: these are in the water and meant to record.
NEREUS_WATCHED = {"OPERATIONAL", "PARTIALLY_FUNCTIONAL", "FAILED", "OFFLINE"}
FULL_REFDES = re.compile(r"^[A-Z0-9]{8}-[A-Z0-9]{5}-[0-9][0-9A-Z]-[A-Z0-9]{9}$")
# The longest gap (minutes) normal for a type on a fixed mount; an instrument on a profiling science pod (SF) or a deep
# profiler (DP) samples only as it passes, so PROFILER_GAP (the shallow profiler's 200 m platform, PC, is fixed). A gap
# longer than this in the day is yellow.
TYPE_GAP = {
    "seismometer": 10, "broadband_seismometer": 10, "short_period_seismometer": 10, "tiltmeter": 10,
    "pressure": 30, "bottom_pressure_tilt": 30, "absolute_pressure_gauge": 30, "low_frequency_hydrophone": 30,
    "hydrophone": 30, "ctd": 60, "dissolved_oxygen": 60, "three_dimensional_current_meter": 60, "velocimeter": 60,
    "adcp": 60, "thermistor": 60, "thermistor_array": 60, "fluorometer": 60, "spectrophotometer": 120, "par": 60,
    "irradiance": 60, "nitrate": 120, "ph": 240, "pco2": 240, "camera": 180, "sonar": 60, "hpies": 240,
}
DEFAULT_GAP = 120
PROFILER_GAP = {"SF": 360, "DP": 720}
# Profiler sensors that sample on some profiles only (the nitrate and SAMI pH and pCO2 on the Axial science pod: 8 to
# 13 hours between samples on a normal day).
PROFILER_TYPE_GAP = {"nitrate": 900, "ph": 900, "pco2": 900}
# By hand: id -> None drops it; id -> dict sets fields ({"gap": 600, "why": "..."}).
OVERRIDES: dict[str, dict | None] = {}


def tls() -> ssl.SSLContext:
    """The system's certificates, else certifi's (this machine's store lacks OOI ERDDAP's issuer)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def check_of(sensor: dict, nereus: dict[str, dict], erddap: set[str]) -> dict:
    """The primary check ("method") and every second one the sensor has: Nereus's hourly check ("data", else
    "file" for the instruments it checks only by their files) and an ERDDAP dataset."""
    access = {a["kind"]: a for a in sensor.get("access", [])}
    if sensor["id"].startswith("EARTHSCOPE-"):
        return {"method": "earthscope", "network": "OO", "station": sensor["id"].split("-")[-1]}
    # A broadband hydrophone's 5-minute MiniSEED files on OOI's raw data server: where its data go, and the record that
    # showed all six stopping at 07:35 UTC on 14 Nov 2026 with the seismometers' 200 Hz (Nereus flagged them 27 hours
    # later).
    refdes = sensor.get("refdes") or ""
    if re.match(r"^[A-Z0-9]{8}-[A-Z0-9]{5}-\d{2}-HYDBB[A-Z]\d{3}$", refdes):
        site, node, _, inst = refdes.split("-")
        return {"method": "rawdata", "path": f"{site}/{node}/{inst}"}
    out: dict = {}
    row = nereus.get(sensor.get("refdes") or "") or {}
    status = lambda kind: (((row.get(f"latest{kind}StatusConnection") or {}).get("status")) or {}).get("code")
    if row.get("dataCheckIsEnabled") and status("Data") in ("GOOD", "BAD", "WARN"):
        out["nereus"] = "data"
    elif row.get("fileCheckIsEnabled") and status("File") in ("GOOD", "BAD", "WARN"):
        out["nereus"] = "file"
    if out.get("nereus"):
        out["refdes"] = sensor["refdes"]
    # The map lists ERDDAP for fewer instruments than it serves (none of the Oregon Offshore profilers).
    dataset = (access.get("erddap") or {}).get("datasetId") or f"ooi-{(sensor.get('refdes') or '').lower()}"
    if dataset in erddap:
        out["dataset"] = dataset
    # A low-frequency hydrophone's channel on its station; a pressure gauge's or current meter's there is not its
    # sample record.
    if (access.get("earthscope") or {}).get("channel") == "HDH":
        a = access["earthscope"]
        return {"method": "earthscope", "network": a.get("network", "OO"), "station": a["station"], "channel": "HDH", **out}
    return {"method": "nereus" if out.get("nereus") else "erddap" if out.get("dataset") else "none", **out}


def watched(sensor: dict, nereus: dict[str, dict]) -> bool:
    if sensor["id"].startswith("EARTHSCOPE-"):
        return True
    refdes = sensor.get("refdes") or ""
    if not FULL_REFDES.match(refdes):
        return False
    status = (nereus.get(refdes) or {}).get("operationalStatusCode")
    return status in NEREUS_WATCHED if status else sensor.get("status") in WATCHED_STATUS


def gap_of(sensor: dict) -> int:
    if sensor["id"].startswith("EARTHSCOPE-"):
        return TYPE_GAP["seismometer"]
    node = (sensor.get("node") or (sensor.get("refdes") or "--").split("-")[1])[:2]
    if node in PROFILER_GAP:
        return max(PROFILER_GAP[node], PROFILER_TYPE_GAP.get(sensor.get("type"), 0))
    return TYPE_GAP.get(sensor.get("type"), DEFAULT_GAP)


def build(sensors: list[dict], nereus: dict[str, dict], erddap: set[str]) -> list[dict]:
    rows = []
    for s in sensors:
        if s["id"] in OVERRIDES and OVERRIDES[s["id"]] is None:
            continue
        if not watched(s, nereus) and s["id"] not in OVERRIDES:
            continue
        row = {"id": s["id"], "name": s["name"], "refdes": s.get("refdes"), "site": s.get("site"), "type": s.get("type"),
               "gap": gap_of(s), "check": check_of(s, nereus, erddap)}
        rows.append({**row, **(OVERRIDES.get(s["id"]) or {})})
    return sorted(rows, key=lambda r: (r["check"]["method"], r["site"] or "", r["id"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensors", default=str(ROOT / "src/atlas_map/public/atlas/sensors.json"))
    ap.add_argument("--out", default=str(Path(__file__).with_name("watchlist.json")))
    args = ap.parse_args()
    from nereus_agent_tools import NereusToolkit
    inv = NereusToolkit(timeout=60).inventory(include_non_rca=True)
    if not inv.get("ok"):
        sys.exit(f"Nereus inventory failed: {inv.get('error')}")
    nereus = {i["designator"]: i for i in inv["instruments"]}
    with urllib.request.urlopen(f"{ERDDAP}/tabledap/allDatasets.csv?datasetID", timeout=120, context=tls()) as r:
        erddap = set(r.read().decode().split("\n")[2:])
    bundle = json.loads(Path(args.sensors).read_text())
    rows = build(bundle["sensors"] if isinstance(bundle, dict) else bundle, nereus, erddap)
    Path(args.out).write_text(json.dumps({"sensors": rows}, indent=1) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["check"]["method"]] = counts.get(r["check"]["method"], 0) + 1
    print(f"{len(rows)} watched: {counts}")


if __name__ == "__main__":
    main()
