#!/usr/bin/env python3
"""New questions whose answers come from source data, with their gold: question types 6 (sensors at a site),
7 (about a sensor), 11 (data date range), 12 (changes), 13 (instrument errors) and 14 (calibration).

Gold is computed from the sources the graph is built from: the instrument inventory and the map's sites
(data/Instruments, the atlas bundle), OOI asset management (deployments, serials, makes, models, calibrations) and the
stations' StationXML (azimuths, channel epochs). The in-situ calibrations of the cabled SCPR are read from its
control log on the PI portal (scpr_calibrations.py) and are added separately.

Each sensor and each site is one entity, wholly in train or in blind (an entity in both would leak what is tuned on
train into blind): entities are grouped by area, ordered by a hash of their ID with a fixed seed, and alternated, so
both halves cover every area. Two phrasings an entity, chosen by the same hash, from names, designators, station
codes and casual descriptions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src/ooi_asset_management"))
from build_asset_metadata import REPO, Repository, calibration_for  # noqa: E402

SEED = "rca-atlas-question-bank-2026-11-17"
SERIAL = "Manufacturer's Serial No./Other Identifier"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
TODAY = NOW[:10]
TYPE_NAMES = {6: "site_sensors", 7: "sensor_info", 11: "data_availability", 12: "changes", 13: "errors", 14: "calibration"}

AREAS = {   # area -> site designators (and inventory locations) it takes in
    "Axial Seamount": ("RS03",), "Southern Hydrate Ridge": ("RS01SUM",), "Oregon Slope Base": ("RS01SLBS", "RS01SBP"),
    "Oregon Offshore": ("CE04OS",), "Oregon Shelf": ("CE02SH",), "Axial Base": ("RS03AXBS", "RS03AXP"),
    "the Axial Central Caldera": ("RS03CCAL",), "the Axial Eastern Caldera": ("RS03ECAL",),
    "the International District": ("RS03INT",), "the ASHES vent field": ("RS03ASHS",),
}
SUB_AREAS = {"Axial Seamount": ("Axial Base", "the Axial Central Caldera", "the Axial Eastern Caldera",
                                 "the International District", "the ASHES vent field")}
CASUAL_AREA = {"Axial Seamount": "axial", "Southern Hydrate Ridge": "hydrate ridge", "Oregon Slope Base": "slope base",
               "Oregon Offshore": "oregon offshore", "Oregon Shelf": "the oregon shelf", "Axial Base": "axial base",
               "the Axial Central Caldera": "central caldera", "the Axial Eastern Caldera": "eastern caldera",
               "the International District": "the international district", "the ASHES vent field": "ashes"}
KINDS = {   # a kind asked about at a site -> instrument types in the inventory
    "seismometers": ("seismometer", "ocean_bottom_seismic_package", "broadband_seismometer", "short_period_seismometer"),
    "hydrophones": ("hydrophone", "low_frequency_hydrophone"), "CTDs": ("ctd",), "cameras": ("camera",),
    "pressure sensors": ("pressure", "absolute_pressure_gauge", "bottom_pressure_tilt", "self_calibrating_pressure_recorder",
                         "bottom_pressure_recorder", "differential_pressure_gauge"),
    "current meters": ("adcp", "velocimeter", "three_dimensional_current_meter"),
    "oxygen sensors": ("dissolved_oxygen",), "pH sensors": ("ph", "thermistor_ph"),
}


# Platforms (site designators) and the nodes on them, as questions name them.
PLATFORMS = {
    "RS01SBPS": ["the Slope Base shallow profiler mooring", "the shallow profiler at slope base"],
    "RS01SBPD": ["the Slope Base deep profiler", "the deep profiler at slope base"],
    "RS01SLBS": ["the Oregon Slope Base seafloor package", "the slope base seafloor instruments"],
    "RS01SUM1": ["the Southern Hydrate Ridge flank", "the hydrate ridge flank site"],
    "RS01SUM2": ["the Southern Hydrate Ridge summit", "the summit of southern hydrate ridge"],
    "RS03AXPS": ["the Axial Base shallow profiler mooring", "the shallow profiler at axial base"],
    "RS03AXPD": ["the Axial Base deep profiler", "the deep profiler at axial base"],
    "RS03AXBS": ["the Axial Base seafloor package", "the axial base seafloor instruments"],
    "CE04OSPS": ["the Oregon Offshore shallow profiler mooring", "the oregon offshore shallow profiler"],
    "CE04OSPD": ["the Oregon Offshore deep profiler", "the deep profiler at oregon offshore"],
    "CE04OSBP": ["the Oregon Offshore benthic experiment package", "the oregon offshore BEP"],
    "CE02SHBP": ["the Oregon Shelf benthic experiment package", "the oregon shelf BEP"],
    "RS03INT1": ["International District hydrothermal field 1", "IDF 1 at axial"],
    "RS03INT2": ["International District hydrothermal field 2", "IDF 2 at axial"],
}
NODE_WORDS = {"LJ": "low-power junction box", "MJ": "medium-power junction box", "PC": "200 m platform", "SF": "shallow profiler",
              "DP": "deep profiler", "PN": "primary node", "LV": "low-voltage node"}


def h(*parts: str) -> int:
    return int(hashlib.sha256("|".join((SEED, *parts)).encode()).hexdigest()[:12], 16)


def pick(options: list[str], *key: str, n: int = 2) -> list[str]:
    order = sorted(range(len(options)), key=lambda i: h(*key, str(i)))
    return [options[i] for i in order[:n]]


def human(day: str) -> str:
    d = datetime.strptime(day[:10], "%Y-%m-%d")
    return f"{d.strftime('%B')} {d.day}, {d.year}"


class Sources:
    def __init__(self):
        self.inv = {json.loads(l)["canonical_id"]: json.loads(l) for l in (ROOT / "data/Instruments/instruments.jsonl").read_text().splitlines() if l.strip()}
        repo = Repository(REPO)
        self.assets, self.vocab, self.cals = repo.assets(), repo.vocab(), repo.calibrations()
        by = defaultdict(dict)
        for row in repo.deployments():
            cur = by[row["Reference Designator"]].get(row["deploymentNumber"])
            if cur is None or int(row.get("versionNumber") or 0) >= int(cur.get("versionNumber") or 0):
                by[row["Reference Designator"]][row["deploymentNumber"]] = row
        self.deps = {r: sorted(v.values(), key=lambda d: int(d["deploymentNumber"])) for r, v in by.items()}
        self.az, self.epochs = self.stationxml()

    def stationxml(self):
        ns = {"s": "http://www.fdsn.org/xml/station/1"}
        az, epochs = {}, defaultdict(list)
        for path in sorted((ROOT / "source_material/stationxml").rglob("OO_*.xml")):
            for st in ET.parse(path).getroot().iterfind(".//s:Station", ns):
                code = st.get("code")
                for ch in st.iterfind("s:Channel", ns):
                    epochs[code].append((ch.get("code"), ch.get("locationCode") or "", (ch.get("startDate") or "")[:10], (ch.get("endDate") or "")[:10]))
                    end = ch.get("endDate") or ""
                    if end and end[:19] <= NOW:
                        continue
                    if ch.get("code", "")[-1] in "N1" and ch.get("code", "")[1] in "HLN":
                        a = ch.findtext("s:Azimuth", namespaces=ns)
                        if a is not None:
                            az.setdefault(code, {})[ch.get("code")] = round(float(a))
        return az, epochs

    def refdes(self, sid: str) -> str | None:
        d = self.inv[sid]
        for n in [sid, *(d.get("aliases") or [])]:
            if n in self.deps:
                return n
        return None

    def deployed(self, sid: str) -> bool:
        return self.inv[sid].get("record_status") not in ("reference_only", "deployment_site_reference", "documented_project_instance")

    def area_of(self, sid: str) -> str | None:
        d = self.inv[sid]
        keys = [sid, *(d.get("aliases") or []), d.get("site") or ""]
        for area, prefixes in sorted(AREAS.items(), key=lambda kv: -max(len(p) for p in kv[1])):
            if any(k.startswith(p) for k in keys for p in prefixes):
                return area
        loc = d.get("location") or ""
        for area in AREAS:
            if area.replace("the ", "").split(" ")[-1] in loc and area.replace("the ", "") in loc:
                return area
        return None

    def serials(self, refdes: str) -> list[tuple[str, str]]:
        out = []
        for d in self.deps.get(refdes, []):
            s = self.assets.get(d.get("sensor.uid", ""), {}).get(SERIAL)
            if s and s not in [x for x, _ in out]:
                out.append((s, d["startDateTime"][:10]))
        return out


def names(src: Sources, sid: str) -> list[str]:
    """Ways a question may name the sensor: its name, its designator, its station code, a casual description."""
    d = src.inv[sid]
    out = [d.get("name") or sid]
    r = src.refdes(sid)
    if r:
        out.append(r)
    m = re.fullmatch(r"EARTHSCOPE-OO-([A-Z0-9]+)", sid)
    if m:
        out += [m.group(1), f"station {m.group(1)}"]
    nm = (d.get("name") or "").lower()
    area = src.area_of(sid)
    kind = (d.get("instrument_type") or "").replace("_", " ")
    # "the fluorometer at oregon offshore" only when it is the only one there (the profilers carry two).
    alike = [s for s in src.inv if src.deployed(s) and src.area_of(s) == area and src.inv[s].get("instrument_type") == d.get("instrument_type")]
    if area and kind and len(alike) == 1:
        out.append(f"the {kind} at {CASUAL_AREA.get(area, area)}")
    if nm:
        out.append(f"the {nm}")
    return list(dict.fromkeys(out))


# System names a past question may use for a sensor (no designator or station code in the question).
SYSTEM_WORDS = {"SCPR": r"\bSCPR", "BOTPT": r"\bBOTPT", "COVIS": r"\bCOVIS", "CAMHD": r"\bCAM ?HD", "PREST": r"\bPREST",
                "HPIES": r"\bHPIES", "TRHPH": r"\bTRHPH", "VEL3D": r"\bVEL3D", "A-0-A": r"\bA-0-A"}


def seen_entities(src: Sources, entities: list[str], bank: Path) -> set[str]:
    """Entities a question already asked names (the train bank): they cannot be blind, having been seen."""
    asked = [json.loads(l)["question"] for l in bank.read_text().splitlines() if l.strip()] if bank.exists() else []
    text = "\n".join(asked)
    low = text.lower()
    seen = set()
    for e in entities:
        if e.startswith(("platform:", "node:")):
            code = e.split(":", 1)[1]
            words = PLATFORMS.get(code, [])
            if re.search(rf"\b{code}\b", text) or any(w.replace("the ", "").lower() in low for w in words):
                seen.add(e)
            continue
        if e.startswith("site:"):
            area = e[5:]
            if area.replace("the ", "").lower() in low or CASUAL_AREA.get(area, "@@").lower() in low:
                seen.add(e)
            continue
        if e not in src.inv:
            continue
        d = src.inv[e]
        ids = [e, *(d.get("aliases") or [])]
        m = re.fullmatch(r"EARTHSCOPE-OO-([A-Z0-9]+)", e)
        if m:
            ids.append(m.group(1))
        if any(re.search(rf"\b{re.escape(i)}\b", text) for i in ids if len(i) >= 4):
            seen.add(e)
            continue
        label = f"{d.get('name') or ''} {d.get('model') or ''} {' '.join(ids)}"
        for word, rx in SYSTEM_WORDS.items():
            if re.search(rx, text, re.I) and re.search(rx, label, re.I):
                seen.add(e)
    return seen


def split_of(entities: dict[str, str], seen: set[str]) -> dict[str, str]:
    """entity -> 'train' or 'blind': seen entities train; the rest alternated by hash within each area."""
    by_area = defaultdict(list)
    for e, area in entities.items():
        if e not in seen:
            by_area[area or "none"].append(e)
    out = {e: "train" for e in seen if e in entities}
    for area, es in by_area.items():
        for i, e in enumerate(sorted(es, key=lambda e: h(e))):
            out[e] = "train" if i % 2 == 0 else "blind"
    return out


def generate(src: Sources) -> list[dict]:
    rows = []

    def q(t, entity, question, gold, kind):
        rows.append({"type": t, "type_name": TYPE_NAMES[t], "entity": entity, "question": question, "gold": gold,
                     "gold_kind": kind, "source": "generated_from_sources", "as_of": TODAY})

    deployed = [s for s in src.inv if src.deployed(s)]
    # 6: sensors at a site, all of them and by kind.
    for area in AREAS:
        # A site takes in its sub-sites: "what sensors are at Axial" is every Axial instrument, not the two the
        # inventory files under Axial Seamount itself (the key had only those).
        here = sorted(s for s in deployed if src.area_of(s) in {area, *SUB_AREAS.get(area, ())})
        if not here:
            continue
        gold = {"sensors": here, "names": [src.inv[s].get("name") for s in here]}
        for text in pick([f"Which instruments are at {area}?", f"what sensors are deployed at {CASUAL_AREA[area]}",
                          f"List every sensor at {area}.", f"what's at {CASUAL_AREA[area]}? all the instruments please"], area):
            q(6, f"site:{area}", text, gold, "sensor_set")
        for kind, types in KINDS.items():
            ks = [s for s in here if src.inv[s].get("instrument_type") in types]
            if ks:
                for text in pick([f"Which {kind} are at {area}?", f"what {kind} are there at {CASUAL_AREA[area]}",
                                  f"How many {kind} does {area} have, and which are they?"], area, kind, n=1):
                    q(6, f"site:{area}", text, {"sensors": ks, "names": [src.inv[s].get("name") for s in ks]}, "sensor_set")

    # 6 at a finer grain: the platforms and the nodes (junction boxes, profilers, 200 m platforms) they carry.
    REF = re.compile(r"((?:RS|CE)\d\d[A-Z0-9]{4})-([A-Z0-9]{5})-")
    where = {}
    for sid in deployed:
        m = next((REF.match(n) for n in [sid, *(src.inv[sid].get("aliases") or [])] if REF.match(n)), None)
        if m:
            where[sid] = (m.group(1), m.group(2))
    for plat, words in PLATFORMS.items():
        on = sorted(s for s, (p, _) in where.items() if p == plat)
        if on:
            gold = {"sensors": on, "names": [src.inv[x].get("name") for x in on]}
            q(6, f"platform:{plat}", f"Which instruments are on {words[0]}?", gold, "sensor_set")
            q(6, f"platform:{plat}", f"what sensors does {words[1]} have", gold, "sensor_set")
    for node in sorted({n for _, n in where.values()}):
        on = sorted(s for s, (_, n) in where.items() if n == node)
        plats = sorted({p for s, (p, n) in where.items() if n == node})
        word = NODE_WORDS.get(node[:2], "node")
        gold = {"sensors": on, "names": [src.inv[x].get("name") for x in on], "platforms": plats}
        q(6, f"node:{node}", f"Which instruments are connected to {node}?", gold, "sensor_set")
        q(6, f"node:{node}", f"what's plugged into the {word} {node}", gold, "sensor_set")

    for sid in deployed:
        r = src.refdes(sid)
        ns = names(src, sid)
        nm = ns[0]
        if r:
            v = src.vocab.get(r, {})
            deps = src.deps[r]
            serials = src.serials(r)
            last = deps[-1]
            # 7: make, model, serial, depth.
            if v.get("Manufacturer") and v.get("Model"):
                for n in pick(ns, sid, "make", n=1):
                    q(7, sid, pick([f"Who makes {n}, and what model is it?", f"what make and model is {n}",
                                    f"Tell me about {n}: who manufactures it?"], sid, "makeq", n=1)[0],
                      {"manufacturer": v["Manufacturer"], "model": v["Model"]}, "facts")
            if serials:
                cur = src.assets.get(last.get("sensor.uid", ""), {}).get(SERIAL)
                for n in pick(ns, sid, "serial", n=1):
                    q(7, sid, pick([f"What is the serial number of {n}?", f"serial number for {n}?",
                                    f"Which serial numbers has {n} had?"], sid, "serq", n=1)[0],
                      {"current_serial": cur, "all_serials": [s for s, _ in serials]}, "facts")
            try:
                depth = float(last.get("deployment_depth") or "")
            except ValueError:
                depth = None
            if depth is not None:
                for n in pick(ns, sid, "depth", n=1):
                    q(7, sid, f"How deep is {n}?", {"depth_m": depth}, "facts")
            # 11: date range of its data (its deployments).
            first = deps[0]["startDateTime"][:10]
            ongoing = not last.get("stopDateTime") or last["stopDateTime"][:19] > NOW
            end = None if ongoing else last["stopDateTime"][:10]
            for n in pick(ns, sid, "range", n=1):
                q(11, sid, pick([f"What date range does {n} have data for?", f"since when has {n} been recording?",
                                 f"When does the data record of {n} start and end?"], sid, "rangeq", n=1)[0],
                  {"first_deployed": first, "ongoing": ongoing, "last_ended": end, "deployments": len(deps)}, "facts")
            # 12: changes (deployments, serial swaps).
            for n in pick(ns, sid, "changes", n=1):
                q(12, sid, pick([f"Has {n} ever been swapped or replaced?", f"What instrument changes has {n} had?",
                                 f"How many times has {n} been deployed, and with which serial numbers?"], sid, "chq", n=1)[0],
                  {"deployments": len(deps), "serials_in_order": [{"serial": s, "from": d} for s, d in serials],
                   "first_deployed": first}, "facts")
            # 14: calibration in force for the latest deployment.
            uid = last.get("sensor.uid", "")
            cal = calibration_for(uid, last["startDateTime"], src.cals) if uid in src.cals else None
            if cal:
                for n in pick(ns, sid, "cal", n=1):
                    q(14, sid, pick([f"When was {n} last calibrated?", f"Which calibration is {n} using in its latest deployment?",
                                     f"what's the calibration date for {n}?"], sid, "calq", n=1)[0],
                      {"calibration_in_force": cal[0], "latest_on_file": src.cals[uid][-1][0], "serial": src.assets.get(uid, {}).get(SERIAL),
                       "calibrations_on_file": [c for c, _ in src.cals[uid]]}, "facts")
        # Seismic stations: orientation (13) and channel epochs (11).
        m = re.fullmatch(r"EARTHSCOPE-OO-([A-Z0-9]+)", sid)
        if m and m.group(1) in src.az:
            code = m.group(1)
            az = src.az[code]
            # Two kinds of orientation issue: components that disagree, and a sensor not turned to north.
            for text in pick([f"Is {code} oriented correctly?", f"What is the azimuth of {code}'s north component?",
                              f"does station {code} have an orientation issue"], sid, "orient", n=1):
                q(13, sid, text, {"azimuths": az, "components_disagree": len(set(az.values())) > 1,
                                  "not_north": any(a % 360 != 0 for a in az.values())}, "facts")
        if m and src.epochs.get(m.group(1)):
            ep = src.epochs[m.group(1)]
            q(11, sid, f"Which channels does {m.group(1)} record, and since when?",
              {"channels": sorted({f"{loc}.{c}" if loc else c for c, loc, _, _ in ep}), "first": min(s for _, _, s, _ in ep if s)}, "facts")

    # The cabled SCPR calibrates itself in place; its calibrations come from its control log (scpr_calibrations.py).
    scpr = ROOT / "runtime_data/SCPR/scpr_calibrations.json"
    if scpr.exists() and "SCPRAAA301" in src.inv:
        log = json.loads(scpr.read_text())
        last = log["calibrations_newest_first"][0]
        gold = {"last_calibration_start": last["start"], "last_calibration_end": last["end"], "minutes": last["minutes"],
                "method": "in-situ deadweight (piston gauge) calibration", "no_calibration_since_through": TODAY}
        for text in ["When was the SCPR at Axial Seamount last calibrated?", "when did the self-calibrating pressure recorder at the central caldera last calibrate",
                     "How recently has the Axial SCPR run an in-situ calibration?"]:
            q(14, "SCPRAAA301", text, gold, "facts")

    disagree = sorted(c for c, a in src.az.items() if len(set(a.values())) > 1)
    not_north = sorted(c for c, a in src.az.items() if any(x % 360 != 0 for x in a.values()))
    for text in ["Which seismic stations have an orientation issue?", "which seismometers are misoriented?",
                 "Are there any OOI seismometers whose horizontal components aren't aligned?"]:
        q(13, "orientation:all", text, {"components_disagree": disagree, "not_north": not_north}, "station_set")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", type=Path, default=HERE / "generated_train.jsonl")
    parser.add_argument("--blind", type=Path, default=HERE / "blind" / "generated_blind.jsonl")
    args = parser.parse_args()
    src = Sources()
    rows = generate(src)
    def area(e):
        if e in src.inv:
            return src.area_of(e)
        kind, code = e.split(":", 1)
        return "platforms" if kind in ("platform", "node") else code
    entities = {r["entity"]: area(r["entity"]) for r in rows}
    seen = seen_entities(src, list(entities), HERE / "question_bank.jsonl")
    split = split_of(entities, seen)
    for i, r in enumerate(rows):
        r["split"] = split[r["entity"]]
        r["id"] = f"gen:{r['type']}:{h(r['entity'], r['question']) % 10**8:08d}"
    args.blind.parent.mkdir(parents=True, exist_ok=True)
    for path, part in ((args.train, "train"), (args.blind, "blind")):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if r["split"] == part), encoding="utf-8")
    count = defaultdict(lambda: defaultdict(int))
    for r in rows:
        count[f"{r['type']} {r['type_name']}"][r["split"]] += 1
    print(json.dumps({"questions": len(rows), "entities": len(entities), "seen_entities_forced_train": len(seen), "by_type": {k: dict(v) for k, v in sorted(count.items())}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
