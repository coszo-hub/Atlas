#!/usr/bin/env python3
"""Link every paper to the RCA sensors and features it names or describes, from its abstract and its full text.

Reads the literature catalog's passages (data/Literature: title, citation and abstract) and the full-text passages
(data/LiteratureFullText), the instrument inventory (data/Instruments: the map's sensors), and a curated list of the
features the sensors watch (vent fields and vents, calderas and rift zones, eruptions, seeps, the margin). Each paper
is linked to

- a sensor it NAMES: its station code (HYS14, AXCC1; "OO.HYS14"), a station range that takes it in ("HYS11-14",
  "AXEC1–AXEC3"), or its OOI reference designator, with or without the port (RS03CCAL-MJ03F-05-BOTPTA301);
- a sensor it DESCRIBES: the sensor's site and its kind of instrument in one passage, within a few hundred characters
  ("a broadband seismometer at Southern Hydrate Ridge"), in a paper from 2009 on that names the RCA, OOI or one of its
  stations somewhere (so the ODP-era seismometers at Hydrate Ridge are not taken for HYS14). Every sensor of that kind
  at that site is linked, with how many shared the description;
- a feature it names (ASHES, the 2015 eruption, the north rift zone, Southern Hydrate Ridge, the deformation front).

Each link keeps the layers it was found in, how many passages, and the best passage as evidence. Writes the
LiteratureLinks collection: papers, sensors (their inventory IDs and designators as aliases, so they join the
instrument records) and features as nodes; the links as edges; one evidence passage per link, embedded for search.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIT = ROOT / "data/Literature"
FULLTEXT = ROOT / "data/LiteratureFullText"
INSTRUMENTS = ROOT / "data/Instruments/instruments.jsonl"
OUTPUT = ROOT / "data/LiteratureLinks"

STATION = re.compile(r"\b(?:OO\.)?(AXAS[12]|AXBA1|AXCC[12]|AXEC[123]|AXID1|HYS1[1-4]|HYSB1|CZ(?:MID|OFF|OSH|SHF))\b")
# "HYS11-14", "HYS11–HYS14", "AXEC1-3", "AXEC1 to AXEC3": every station between the two.
RANGE = re.compile(r"\b(AXAS|AXCC|AXEC|HYS)(\d{1,2})\s*(?:[-‐‑‒–—]|to)\s*(?:\1)?(\d{1,2})\b")
REFDES = re.compile(r"\b((?:RS|CE)\d\d[A-Z0-9]{4})-?([A-Z0-9]{5})-(?:(\d\d)-)?([A-Z0-9]{9})\b")
RCA_SIGNAL = re.compile(r"Regional Cabled Array|[Cc]abled [Aa]rray|Ocean Observatories Initiative|\bOOI\b|\bRSN\b|"
                        r"Regional Scale Nodes?|NEPTUNE|\b(?:RS0[13]|CE0[24])[A-Z0-9]{4}\b|" + STATION.pattern)
AXIAL = re.compile(r"\bAxial\b")

# Where each sensor is, by site designator, as papers write it; the Axial names count only beside "Axial".
SITE_NAMES = {
    "RS01SLBS": (r"Slope Base", False), "RS01SBPS": (r"Slope Base", False), "RS01SBPD": (r"Slope Base", False),
    "RS01SUM1": (r"Southern Hydrate Ridge|south(?:ern)? summit of Hydrate Ridge|Hydrate Ridge summit|\bSHR\b", False),
    "RS01SUM2": (r"Southern Hydrate Ridge|south(?:ern)? summit of Hydrate Ridge|Hydrate Ridge summit|\bSHR\b", False),
    "RS03AXBS": (r"Axial Base|base of Axial", False), "RS03AXPS": (r"Axial Base|base of Axial", False),
    "RS03AXPD": (r"Axial Base|base of Axial", False),
    "RS03CCAL": (r"Central Caldera", True), "RS03ECAL": (r"Eastern Caldera", True),
    "RS03INT1": (r"International District", True), "RS03INT2": (r"International District", True),
    "RS03ASHS": (r"\bASHES\b", True),
    "CE02SHBP": (r"Oregon Shelf", False), "CE02SHSP": (r"Oregon Shelf", False),
    "CE04OSBP": (r"Oregon Offshore", False), "CE04OSPS": (r"Oregon Offshore", False), "CE04OSPD": (r"Oregon Offshore", False),
}
LOCATION_SITE = {  # inventory locations without a designator (the OO stations, project instruments)
    "Southern Hydrate Ridge Summit": "RS01SUM1", "Southern Hydrate Ridge": "RS01SUM1", "Oregon Slope Base": "RS01SLBS",
    "Oregon Slope Base Seafloor": "RS01SLBS", "Axial Seamount Base": "RS03AXBS", "Axial Seamount Central Caldera": "RS03CCAL",
    "Central Caldera": "RS03CCAL", "Axial Seamount Eastern Caldera": "RS03ECAL", "Axial Seamount International District": "RS03INT1",
    "ASHES Hydrothermal Field, Axial Seamount": "RS03ASHS", "Oregon Shelf": "CE02SHBP", "Oregon Offshore": "CE04OSBP",
    "Oregon Offshore Cabled Benthic Experiment Package": "CE04OSBP", "Oregon Offshore Cabled Shallow Profiler Mooring": "CE04OSPS",
    "Oregon Offshore Cabled Deep Profiler Mooring": "CE04OSPD", "Axial Seamount Profiler": "RS03AXPS", "Axial Seamount Deep Profiler": "RS03AXPD",
}
# How papers name each kind of instrument.
KIND_WORDS = {
    "seismometer": r"seismomet\w*|\bOBSs?\b|ocean[- ]bottom seismo\w*",
    "ocean_bottom_seismic_package": r"seismomet\w*|\bOBSs?\b",
    "hydrophone": r"hydrophones?", "low_frequency_hydrophone": r"hydrophones?",
    "bottom_pressure_recorder": r"(?:bottom )?pressure (?:recorder|sensor|gauge)s?|\bBPRs?\b",
    "absolute_pressure_gauge": r"pressure (?:recorder|sensor|gauge)s?|\bBPRs?\b|self[- ]calibrating pressure|A-0-A",
    "pressure": r"pressure (?:recorder|sensor|gauge)s?|\bBPRs?\b|\bBOTPTs?\b|tilt(?:meter)?s?",
    "self_calibrating_pressure_recorder": r"self[- ]calibrating pressure|\bSCPRs?\b", "self_calibrating_pressure_sensor": r"self[- ]calibrating pressure",
    "differential_pressure_gauge": r"differential pressure", "bottom_pressure_tilt": r"\bBOTPTs?\b|tilt(?:meter)?s?",
    "tiltmeter": r"tilt(?:meter)?s?", "ctd": r"\bCTDs?\b", "adcp": r"\bADCPs?\b|acoustic Doppler current profiler",
    "velocimeter": r"current meters?|velocimeters?|\bVEL3D", "three_dimensional_current_meter": r"current meters?|velocimeters?|\bVEL3D",
    "camera": r"cameras?|CamHD|HD video", "sonar": r"sonar|\bCOVIS\b", "mass_spectrometer": r"mass spectrometers?",
    "fluorometer": r"fluorometers?", "dissolved_oxygen": r"(?:dissolved )?oxygen (?:sensor|optode)s?|optodes?",
    "ph": r"\bpH (?:sensor|probe)s?", "thermistor_ph": r"\bpH\b", "pco2": r"pCO2", "spectrophotometer": r"spectrophotometers?",
    "nitrate": r"nitrate (?:sensor|analy[sz]er)s?", "par": r"\bPAR\b", "irradiance": r"irradiance", "thermistor": r"thermistors?",
    "thermistor_array": r"thermistors?", "osmotic_sampler": r"osmo ?samplers?", "fluid_sampler": r"fluid samplers?",
    "dna_sampler": r"DNA samplers?", "das": r"distributed acoustic sensing|\bDAS\b", "fiber_optic_strainmeter": r"strainmeters?",
    "hpies": r"\bHPIES\b|inverted echo sounders?", "acoustic_ranging_station": r"acoustic (?:ranging|extensometer)|\bFETCH\b",
    "geodetic_and_seismic_sensor_module": r"geodetic|seismomet\w*", "dissolved_gas": r"dissolved gas",
}
NEAR = 300   # characters between a site's name and the instrument's

# Instruments papers name by their system rather than a code: (name, pattern, which sensors, context the passage needs).
# One sensor: the name names it. Several: the one whose site is written near the name; with no site nearby, the
# passage describes them all (the count is kept). A sensor without a site is chosen by its own words (DAS by year).
def _model(*words):
    return lambda d: any(w.lower() in f"{d.get('name') or ''} {d.get('model') or ''} {d['canonical_id']}".lower() for w in words)


SYSTEMS = [   # (name, pattern, which sensors, context the passage needs, counts only in a paper naming the RCA/OOI)
    ("COVIS", r"\bCOVIS\b|Cabled Observatory Vent Imaging Sonar", _model("COVIS"), r"ASHES|Axial", False),
    ("CamHD", r"\bCam ?HD\b|HD (?:video )?camera", _model("CAMHD", "HD Video Camera"), r"Axial|ASHES|Mushroom", True),
    ("A-0-A", r"\bA-?0-?A\b", _model("A-0-A", "AOABP"), r"Axial|pressure", False),
    ("SCPR", r"\bSCPRs?\b|[Ss]elf[- ][Cc]alibrating [Pp]ressure [Rr]ecorders?", _model("SCPR", "Self-Calibrating Pressure Rec"), r"Axial|Oregon|Cascadia|COSZO", True),
    ("BOTPT", r"\bBOTPTs?\b|[Bb]ottom [Pp]ressure (?:and |& )?[Tt]ilt|BPR/[Tt]ilt", _model("BPR/Tilt", "BOTPT"), None, False),
    # Axial's pressure records in general words ("seafloor pressure data from the Cabled Array"): the BOTPTs, in a paper
    # naming the RCA, from 2015 on (the autonomous BPRs before them are not these).
    ("Axial pressure", r"(?:[Ss]eafloor|[Bb]ottom) pressure (?:data|records?|recorders?|measurements|sensors?|gauges?|time series)|\bBPRs?\b",
     lambda d: _model("BPR/Tilt", "BOTPT")(d) and d["canonical_id"].startswith(("RS03CCAL", "RS03ECAL", "RS03INT", "RS03ASHS")),
     r"Axial|caldera", True),
    ("PREST", r"\bPRESTs?\b|[Tt]idal (?:[Ss]eafloor )?[Pp]ressure|SBE ?54", _model("PREST", "Tidal"), None, True),
    ("HPIES", r"\bHPIES\b", _model("HPIES"), None, False),
    ("OsmoSampler", r"[Oo]smo ?[Ss]amplers?|osmotic (?:fluid )?sampler", _model("OsmoSampler", "Osmotic"), None, True),
    ("mass spectrometer", r"[Mm]ass [Ss]pectrometers?|\bMASSP\b", _model("Mass Spec"), None, True),
    ("RAS", r"\bRAS\b|[Rr]emote [Aa]ccess (?:[Ff]luid )?[Ss]ampler", _model("Remote Access Fluid", "RASFL"), r"International District|Axial", True),
    ("MARUM sonars", r"[Oo]verview [Ss]onar|\bSHROS\b|[Rr]otary [Ss]onar", _model("Overview Sonar", "Rotary Sonar"), r"Hydrate Ridge|\bSHR\b", True),
    ("MARUM camera", r"MARUM (?:camera|video)|pan[- ]tilt camera", _model("MARUM Camera"), r"Hydrate Ridge|\bSHR\b", True),
    ("echosounder", r"\bZPLSC\b|EK-?60|[Bb]io-?acoustic [Ss]onar|[Ee]cho ?sounders?", _model("ZPLSC", "EK-60"), r"Endurance|Oregon|Cabled Array", True),
    ("FETCH", r"\bFETCH\b|\bFetch (?=East|West|North|South|transponder|station|instrument)|[Aa]coustic (?:ranging|extensometer|transponders?)",
     _model("FETCH", "Acoustic Transponders"), r"Axial|caldera", False),
    ("strainmeter", r"(?:[Ss]eafloor|[Oo]ptical[- ]fib(?:er|re)) strainmeters?|[Oo]ptical[- ]fib(?:er|re) (?:strain|interferometer)|fib(?:er|re) interferometers?",
     _model("STRAINMETER"), r"Oregon|Newport|Cascadia|Slope Base|Hydrate Ridge|accretionary", False),
    ("benchmarks", r"\bO[1-6]\b", _model("COSZO-BPR-O"), r"benchmarks?|ASCPR", False),
    # The profilers are platforms: a paper on "the Slope Base shallow profiler" describes the instruments it carries.
    ("shallow profiler", r"[Ss]hallow[- ][Pp]rofil(?:er|ing)|[Pp]rofiling (?:mooring|platform)|\bSF0[13][AB]\b",
     lambda d: d["canonical_id"][:8] in ("RS01SBPS", "RS03AXPS", "CE04OSPS"), None, True),
    ("deep profiler", r"[Dd]eep[- ][Pp]rofil(?:er|ing)|McLane (?:moored )?profiler|\bDP0[13][AB]\b",
     lambda d: d["canonical_id"][:8] in ("RS01SBPD", "RS03AXPD", "CE04OSPD"), None, True),
    ("DAS", r"[Dd]istributed [Aa]coustic [Ss]ensing|\bDAS\b", lambda d: d.get("instrument_type") in ("das", "distributed_fiber_sensing"),
     r"Ocean Observatories Initiative|\bOOI\b|Regional Cabled Array|\bRCA\b|Cabled Array", False),
]
# Which DAS deployment a passage means, by its words; else the 2021 community test, the dataset most papers use.
# A bare year is not enough: a 2025 paper's own citation would read as the 2025 deployment.
DAS_BY = [(r"multi-?span|beyond (?:optical )?repeaters?|Nokia|(?:November|December) 2025|2025[–-]2026", ("PI-DAS25",)),
          (r"OptoDAS|(?:April|May|in) 2024", ("PI-DAS24",)),
          # RAPID is the 2021 dataset's name (Wilcock, 2023); OptaSense was one of the 2021 interrogators too.
          (r"^(?!.*(?:2021|RAPID|community)).*OptaSense", ("PI-DAS-OPTASENSE",)),
          (r"2021|community|RAPID|QuantX|DTS|.", ("RCA-DAS-2021-COMMUNITY-TEST",))]

# Features the sensors watch: (id, name, pattern, needs "Axial" in the passage).
FEATURES = [
    ("FEATURE-axial-seamount", "Axial Seamount", r"Axial (?:[Ss]eamount|[Vv]olcano)", False),
    ("FEATURE-axial-caldera", "Axial Seamount summit caldera", r"(?:summit )?caldera", True),
    ("FEATURE-ashes", "ASHES vent field", r"\bASHES\b", True),
    ("FEATURE-international-district", "International District vent field", r"International District", True),
    ("FEATURE-axial-north-rift", "Axial Seamount north rift zone", r"north(?:ern)? rift", True),
    ("FEATURE-axial-south-rift", "Axial Seamount south rift zone", r"south(?:ern)? rift", True),
    ("FEATURE-axial-magma-reservoir", "Axial Seamount magma reservoir", r"magma (?:reservoir|chamber)|melt (?:lens|sill)|\bAMC\b", True),
    ("FEATURE-axial-ring-faults", "Axial Seamount caldera ring faults", r"ring[- ]faults?|caldera faults?", True),
    ("FEATURE-axial-eruption-1998", "Axial Seamount 1998 eruption", r"1998 (?:eruption|lava)|eruption (?:of|in) (?:January )?1998", True),
    ("FEATURE-axial-eruption-2011", "Axial Seamount 2011 eruption", r"2011 (?:eruption|lava)|eruption (?:of|in) (?:April )?2011", True),
    ("FEATURE-axial-eruption-2015", "Axial Seamount 2015 eruption", r"2015 (?:eruption|lava)|eruption (?:of|in) (?:April )?2015", True),
    ("FEATURE-vent-inferno", "Inferno vent (ASHES)", r"\bInferno\b", True),
    ("FEATURE-vent-mushroom", "Mushroom vent (ASHES)", r"\bMushroom\b", True),
    ("FEATURE-vent-el-gordo", "El Gordo vent (International District)", r"El Gordo", True),
    ("FEATURE-vent-diva", "Diva vent (International District)", r"\bDiva\b", True),
    ("FEATURE-vent-escargot", "Escargot vent (International District)", r"\bEscargot\b", True),
    ("FEATURE-vent-marker-113", "Marker 113 vent", r"Marker[- ]113", True),
    ("FEATURE-vent-marker-33", "Marker 33 vent", r"Marker[- ]33", True),
    ("FEATURE-coaxial-segment", "CoAxial segment", r"CoAxial (?:segment|site)", False),
    ("FEATURE-juan-de-fuca-ridge", "Juan de Fuca Ridge", r"Juan de Fuca Ridge", False),
    ("FEATURE-cobb-hotspot", "Cobb hotspot", r"Cobb (?:hot ?spot|hot spot)", False),
    ("FEATURE-hydrate-ridge", "Hydrate Ridge", r"Hydrate Ridge", False),
    ("FEATURE-southern-hydrate-ridge", "Southern Hydrate Ridge summit", r"Southern Hydrate Ridge|south(?:ern)? summit of Hydrate Ridge|\bSHR\b", False),
    ("FEATURE-pinnacle", "Pinnacle (Southern Hydrate Ridge)", r"\bPinnacle\b", False),
    ("FEATURE-pythias-oasis", "Pythia's Oasis seep", r"Pythia['’]?s Oasis", False),
    ("FEATURE-slope-base", "Oregon Slope Base", r"Slope Base", False),
    ("FEATURE-deformation-front", "Cascadia deformation front", r"deformation front", False),
    ("FEATURE-cascadia-subduction-zone", "Cascadia subduction zone", r"Cascadia (?:subduction zone|megathrust|margin)", False),
    ("FEATURE-oregon-shelf", "Oregon shelf", r"Oregon (?:shelf|Shelf)", False),
]


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def stable(prefix: str, text: str) -> str:
    return prefix + hashlib.sha256(text.encode()).hexdigest()[:20]


def snippet(text: str, start: int, end: int, width: int = 220) -> str:
    a, b = max(0, start - width), min(len(text), end + width)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def sensors() -> tuple[dict, dict, dict, dict]:
    """Sensor records; code -> sensor ids; designator (with and without port) -> sensor ids; place -> sensor ids by kind,
    where a place is a site designator (as SITE_NAMES writes it) or a node ("NODE:LJ01B": the junction box or
    platform a paper may name instead of the site)."""
    rec, by_code, by_refdes, by_site = {}, defaultdict(set), defaultdict(set), defaultdict(lambda: defaultdict(set))
    for d in read_jsonl(INSTRUMENTS):
        sid = d["canonical_id"]
        rec[sid] = d
        names = [sid, *(d.get("aliases") or [])]
        m = re.fullmatch(r"EARTHSCOPE-OO-([A-Z0-9]+)", sid)
        if m:
            by_code[m.group(1)].add(sid)
        site = None
        for n in names:
            r = REFDES.fullmatch(n)
            if r:
                by_refdes[n].add(sid)
                by_refdes[f"{r.group(1)}-{r.group(2)}-{r.group(4)}"].add(sid)
                by_refdes[f"{r.group(1)}-{r.group(4)}"].add(sid)
                site = site or r.group(1)
        site = site or d.get("site") or LOCATION_SITE.get(d.get("location") or "")
        node = d.get("node") or next((r.group(2) for n in names if (r := REFDES.fullmatch(n))), None)
        kind = d.get("instrument_type")
        if kind in KIND_WORDS and d.get("record_status") not in ("reference_only", "deployment_site_reference"):
            if site in SITE_NAMES:
                by_site[site][kind].add(sid)
            if node:
                by_site[f"NODE:{node}"][kind].add(sid)
    return rec, by_code, by_refdes, by_site


def passages():
    """(paper id, layer, chunk id, page, text) for every abstract-layer and full-text passage."""
    for c in read_jsonl(LIT / "chunks.jsonl"):
        if c.get("document_type") == "literature_work":
            yield c["document_id"], "abstract", c["chunk_id"], None, c.get("text") or ""
    for c in read_jsonl(FULLTEXT / "chunks.jsonl"):
        yield c["document_id"], "fulltext", c["chunk_id"], c.get("page"), c.get("text") or ""


def collect(rows=None) -> tuple[dict, dict, dict]:
    """Every paper's candidate links to sensors and features, each with the passages that make it."""
    rec, by_code, by_refdes, by_site = sensors()
    papers = {d["document_id"]: d for d in read_jsonl(LIT / "documents.jsonl")}
    site_rx = {s: (re.compile(rf"{p}|\b{s}\b"), axial) for s, (p, axial) in SITE_NAMES.items()}
    site_rx.update({place: (re.compile(rf"\b{place[5:]}\b"), False) for place in by_site if place.startswith("NODE:")})
    kind_rx = {k: re.compile(p) for k, p in KIND_WORDS.items()}
    feat_rx = [(fid, name, re.compile(p), axial) for fid, name, p, axial in FEATURES]

    # Which papers name the RCA anywhere (the condition for a description to count).
    rca_paper = set()
    rows = rows if rows is not None else list(passages())
    for pid, _, _, _, text in rows:
        if RCA_SIGNAL.search(text):
            rca_paper.add(pid)

    # Each system's sensors, and each sensor's site pattern (to choose among several).
    systems = []
    for name, pattern, select, needs, rca_only in SYSTEMS:
        ids = [sid for sid, d in rec.items() if select(d)]
        if ids:
            systems.append((name, re.compile(pattern), ids, re.compile(needs) if needs else None, rca_only))
    site_patterns = {k: re.compile(rf"{v[0]}|\b{k}\b") for k, v in SITE_NAMES.items()}
    site_of = {}
    for sid, d in rec.items():
        r = next((REFDES.fullmatch(n) for n in [sid, *(d.get("aliases") or [])] if REFDES.fullmatch(n)), None)
        site = (r.group(1) if r else None) or d.get("site") or LOCATION_SITE.get(d.get("location") or "")
        if site in site_patterns:
            site_of[sid] = site_patterns[site]

    links: dict[tuple, dict] = {}

    def add(pid, target, kind, layer, cid, page, text, span, share=None):
        key = (pid, target)
        link = links.setdefault(key, {"paper": pid, "target": target, "kinds": set(), "layers": set(), "passages": set(),
                                      "evidence": None, "evidence_rank": 9, "shared_with": None, "hits": []})
        if cid not in link["passages"]:
            link["hits"].append({"layer": layer, "chunk": cid, "page": page, "text": text, "span": span, "kind": kind, "share": share})
        link["kinds"].add(kind)
        link["layers"].add(layer)
        link["passages"].add(cid)
        rank = {"named": 0, "range": 1, "designator": 0, "system": 1, "described": 3, "feature": 2}[kind] + (0 if layer == "fulltext" else 0.5)
        if rank < link["evidence_rank"]:
            link.update(evidence=snippet(text, *span), evidence_rank=rank, evidence_chunk=cid, evidence_layer=layer, evidence_page=page)
        if share:
            link["shared_with"] = share

    for pid, layer, cid, page, text in rows:
        if pid not in papers:
            continue
        axial = bool(AXIAL.search(text))
        for m in STATION.finditer(text):
            for sid in by_code.get(m.group(1), ()):
                add(pid, sid, "named", layer, cid, page, text, m.span())
        for m in RANGE.finditer(text):
            prefix, a, b = m.group(1), int(m.group(2)), int(m.group(3))
            if a < b <= a + 5:
                for n in range(a, b + 1):
                    for sid in by_code.get(f"{prefix}{n}", ()):
                        add(pid, sid, "range", layer, cid, page, text, m.span())
        for m in REFDES.finditer(text):
            for key in (m.group(0), f"{m.group(1)}-{m.group(2)}-{m.group(4)}", f"{m.group(1)}-{m.group(4)}"):
                for sid in by_refdes.get(key, ()):
                    add(pid, sid, "designator", layer, cid, page, text, m.span())
        year = papers[pid].get("publication_year") or 0
        for name, rx, ids, needs, rca_only in systems:
            m = rx.search(text)
            if not m or (needs and not needs.search(text)) or (rca_only and pid not in rca_paper):
                continue
            if name == "Axial pressure" and year < 2015:
                continue
            if name == "DAS":
                for words, chosen in DAS_BY:
                    if re.search(words, text, re.S):
                        ids = [i for i in chosen if i in rec]
                        break
            kind = "described" if name.endswith("profiler") else "system"
            if len(ids) == 1:
                add(pid, ids[0], kind, layer, cid, page, text, m.span())
                continue
            window = text[max(0, m.start() - 2 * NEAR): m.end() + 2 * NEAR]
            near = [i for i in ids if site_of.get(i) and site_of[i].search(window)]
            if kind == "described":
                # A profiler's instruments are those of the kinds written near it ("its CTD and oxygen optode").
                near = [i for i in near if (k := rec[i].get("instrument_type")) in kind_rx and kind_rx[k].search(window)]
            if near:
                for i in near:
                    add(pid, i, kind, layer, cid, page, text, m.span(), share=len(near) if len(near) > 1 else None)
            elif pid in rca_paper and kind == "system":
                # No site beside the name: the sensors in the region the passage is about (Axial, Hydrate Ridge, Slope
                # Base), else all of them.
                caldera = re.search(r"caldera|summit", text, re.I)
                region = [i for i in ids if (AXIAL.search(text) and i.startswith("RS03") and not (caldera and i.startswith("RS03AXBS")))
                          or (re.search(r"Hydrate Ridge|\bSHR\b", text) and i.startswith("RS01SUM"))
                          or (re.search(r"Slope Base", text) and i.startswith(("RS01SLBS", "RS01SBP")))] or ids
                for i in region:
                    add(pid, i, "described", layer, cid, page, text, m.span(), share=len(region))
        if pid in rca_paper and year >= 2009:
            for site, (rx, needs_axial) in site_rx.items():
                if needs_axial and not axial:
                    continue
                for sm in rx.finditer(text):
                    window = text[max(0, sm.start() - NEAR): sm.end() + NEAR]
                    for kind, ids in by_site.get(site, {}).items():
                        km = kind_rx[kind].search(window)
                        if km:
                            for sid in ids:
                                add(pid, sid, "described", layer, cid, page, text, sm.span(), share=len(ids))
        for fid, _, rx, needs_axial in feat_rx:
            if needs_axial and not axial:
                continue
            fm = rx.search(text)
            if fm:
                add(pid, fid, "feature", layer, cid, page, text, fm.span())

    return links, rec, papers


# Whether a paper used a sensor's data or only mentions it. A passage reads as use when it talks about data, records,
# waveforms, figures or what the authors did near the sensor's name; a reference list (many years together) does not.
USE = re.compile(r"""\b(?:we|our)\b[^.]{0,120}?\b(?:use[ds]?|using|analy[sz]\w*|process\w*|examin\w*|download\w*|comput\w*|appl(?:y|ied)|select\w*|stack\w*|correlat\w*|invert\w*|detect\w*|locat\w*|measur\w*|compar\w*|obtain\w*|retriev\w*|record\w*|focus\w*|consider\w*|investigat\w*|exploit\w*)\b
|\bdata\s+(?:from|recorded|collected|were|was|at)\b|\b(?:recorded|measured|observed|detected|captured|imaged|collected|acquired|monitored)\s+(?:by|at|on|with|from|using)\b|\brecords?\s+(?:from|of)\b
|\bwaveforms?\b|\bspectrograms?\b|\btime[- ]series\b|\bFig(?:ure|s?\.)\s*S?\d|\b(?:were|was|is|are)\s+used\b|\busing\s+(?:data|the|records|observations|measurements|recordings|\w+\s+data)\b
|\bdata\s?sets?\b|\bdatasets?\b|\bstations?\b[^.]{0,40}\b(?:used|analy)""", re.I | re.X)
YEARS = re.compile(r"\b(?:19|20)\d\d[a-z]?\b")
# Titles of overviews, reviews and plans: such a paper describes the observatory's sensors rather than analyzing them
# (an "overview of ambient sound using OOI hydrophones" analyzes data, so a title saying "using" or "data" is not one).
OVERVIEW = re.compile(r"Ocean Observatories Initiative$|\breview\b|[Ll]essons [Ll]earned|[Dd]ecadal [Pp]rogress|[Ee]stablishing|[Ss]ustained|"
                      r"[Ff]easibility|[Nn]ext [Dd]ecade|[Nn]ew [Ee]ra|[Pp]erspective|[Ww]hite [Pp]aper|[Ww]orkshop|[Ss]cience [Pp]lan|[Tt]oward|[Oo]pportunit", re.I)
OVERVIEW_WORD = re.compile(r"\b(?:overview|potential|review|introduction)\b", re.I)
TITLE_DATA = re.compile(r"\b(?:using|from|with|recorded|recordings|observations?|observed|data|monitoring|measur\w+)\b", re.I)
CODED = {"named", "range", "designator"}


def is_overview(title: str) -> bool:
    return bool(OVERVIEW.search(title)) or (bool(OVERVIEW_WORD.search(title)) and not TITLE_DATA.search(title))


RCA_WORDS = re.compile(r"Regional Cabled Array|[Cc]abled [Aa]rray|Ocean Observatories Initiative|\bOOI\b|\bRCA\b|cabled observatory", re.I)


def judge_sensor(link: dict, paper: dict, abstract: str = "") -> tuple[str | None, str, dict]:
    """'used', 'mentioned' or None (a description too vague to keep), why, and the passage that shows it best."""
    hits = link["hits"]
    kinds = {h["kind"] for h in hits}
    coded, system = bool(kinds & CODED), "system" in kinds
    use = []
    for h in hits:
        a, z = h["span"]
        window = h["text"][max(0, a - 350): z + 350]
        h["use"] = bool(USE.search(window)) and len(YEARS.findall(window)) < 8
        use.append(h["use"])
    nuse, n = sum(use), len(hits)
    fulltext = any(h["layer"] == "fulltext" for h in hits)
    abstract_use = any(h["use"] for h in hits if h["layer"] == "abstract")
    share = min((h["share"] or 1) for h in hits)
    year = paper.get("publication_year") or 0
    best = sorted(hits, key=lambda h: (not h["use"], h["kind"] not in CODED, h["kind"] != "system", h["layer"] != "fulltext"))[0]
    if year and year < 2013:
        return ("mentioned" if coded or system else None), "published before the cabled sensors", best
    if is_overview(paper.get("title") or ""):
        specific = coded or system or min((h["share"] or 1) for h in hits) <= 2
        return ("mentioned" if specific else None), "an overview, review or plan", best
    if not fulltext:   # the abstract alone: an abstract that names an instrument is about work with it
        if coded or system:
            return "used", "its abstract names it", best
        return ("used", "its abstract describes it in use", best) if share <= 2 and abstract_use else (None, "", best)
    if coded:
        if n >= 3 or nuse >= 1:
            return "used", f"named in {n} passages, {nuse} about data", best
        # A table or map of the stations used, in a paper whose abstract is about RCA data.
        table = any(len(set(STATION.findall(h["text"]))) >= 3 for h in hits)
        if table and RCA_WORDS.search(abstract) and USE.search(abstract):
            return "used", "listed among the stations of a paper on RCA data", best
        return "mentioned", "named once, not about data", best
    if system:
        if nuse >= 2 or abstract_use:
            return "used", f"named in {n} passages, {nuse} about data", best
        return "mentioned", "named without its data", best
    if share <= 2:
        if nuse >= 2 or abstract_use:
            return "used", f"described in {n} passages, {nuse} about data", best
        return ("mentioned", "described, not about data", best) if nuse else (None, "", best)
    if (abstract_use and nuse >= 3) or nuse >= 6:
        return "used", f"its kind at its site described in {n} passages ({share} sensors alike)", best
    return None, "", best


# Methods and concepts (vocabulary.json): a paper applies a method or studies a concept its title names, its abstract
# names, or many of its full-text passages use; an entry papers name as their setting (background) needs more.
TOPIC_ABSTRACT, TOPIC_PASSAGES, TOPIC_SHARE = 1, 12, 0.25
BACKGROUND_ABSTRACT, BACKGROUND_SHARE = 2, 0.4

# Study sites: (id, name, words in a title or abstract, the inventory sites whose used sensors count).
SITES = [
    ("SITE-axial-seamount", "Axial Seamount", r"Axial (?:[Ss]eamount|[Vv]olcano|caldera)|\bAxial\b", ("RS03",)),
    ("SITE-ashes", "ASHES vent field", r"\bASHES\b|Mushroom vent|Inferno vent", ("RS03ASHS",)),
    ("SITE-international-district", "International District vent field", r"International District", ("RS03INT",)),
    ("SITE-axial-central-caldera", "Axial Central Caldera", r"Central Caldera|caldera cent(?:er|re)", ("RS03CCAL",)),
    ("SITE-axial-eastern-caldera", "Axial Eastern Caldera", r"Eastern Caldera", ("RS03ECAL",)),
    ("SITE-axial-base", "Axial Base", r"Axial Base|base of Axial", ("RS03AXBS", "RS03AXP")),
    ("SITE-southern-hydrate-ridge", "Southern Hydrate Ridge", r"[Ss]outh(?:ern)? Hydrate Ridge|\bSHR\b|[Ss]outh(?:ern)? [Ss]ummit of Hydrate Ridge", ("RS01SUM",)),
    ("SITE-northern-hydrate-ridge", "Northern Hydrate Ridge", r"[Nn]orth(?:ern)? Hydrate Ridge|\bNHR\b", ()),
    ("SITE-hydrate-ridge", "Hydrate Ridge", r"Hydrate Ridge", ()),
    ("SITE-oregon-slope-base", "Oregon Slope Base", r"Slope Base", ("RS01SLBS", "RS01SBP")),
    ("SITE-oregon-shelf", "Oregon Shelf", r"Oregon (?:continental )?(?:[Ss]helf|inner shelf|mid-?shelf)|shelf off (?:the coast of )?(?:central )?Oregon|central Oregon (?:continental )?shelf|Newport (?:[Hh]ydrographic )?[Ll]ine|\bNH-?(?:10|20|25)\b|Endurance Array", ("CE02SH",)),
    ("SITE-oregon-offshore", "Oregon Offshore", r"Oregon Offshore", ("CE04OS",)),
]
SITE_PARENT = {"SITE-ashes": "SITE-axial-seamount", "SITE-international-district": "SITE-axial-seamount",
               "SITE-axial-central-caldera": "SITE-axial-seamount", "SITE-axial-eastern-caldera": "SITE-axial-seamount",
               "SITE-axial-base": "SITE-axial-seamount", "SITE-southern-hydrate-ridge": "SITE-hydrate-ridge",
               "SITE-northern-hydrate-ridge": "SITE-hydrate-ridge"}


def sentence(text: str, span: tuple[int, int], width: int = 260) -> str:
    return snippet(text, span[0], span[1], width)


def paper_topics(pid: str, paper: dict, abstract: str, full: list[str], vocabulary: list[dict]) -> list[dict]:
    title = paper.get("title") or ""
    out = []
    for e in vocabulary:
        rx = e["rx"]
        in_title = bool(rx.search(title))
        a = list(rx.finditer(abstract))
        f = [t for t in full if rx.search(t)]
        share = len(f) / len(full) if full else 0
        if e["background"]:
            ok = in_title or len(a) >= BACKGROUND_ABSTRACT or (full and share >= BACKGROUND_SHARE)
        else:
            ok = in_title or len(a) >= TOPIC_ABSTRACT or (full and (len(f) >= TOPIC_PASSAGES or share >= TOPIC_SHARE))
        if not ok:
            continue
        if a:
            evidence, where = sentence(abstract, a[0].span()), "abstract"
        elif f:
            m = rx.search(f[0])
            evidence, where = sentence(f[0], m.span()), "full text"
        else:
            evidence, where = title, "title"
        out.append({"entry": e, "in_title": in_title, "abstract_mentions": len(a), "fulltext_passages": len(f),
                    "fulltext_share": round(share, 2), "evidence": evidence, "evidence_layer": where})
    return out


def paper_sites(paper: dict, abstract: str, used_sensors: list[str], site_of_sensor) -> list[tuple[str, str]]:
    """Study sites: named in the title or abstract, or where the sensors it used are (when they are at one or two sites)."""
    text = f"{paper.get('title') or ''} {abstract}"
    found = {}
    for sid, _, words, _ in SITES:
        if re.search(words, text):
            found[sid] = "named in its title or abstract"
    places = {site_of_sensor(s) for s in used_sensors} - {None}
    groups = {p[:4] for p in places}
    if places and len(groups) == 1:   # sensors spread over Axial and the margin say nothing of one site
        for sid, _, _, prefixes in SITES:
            if prefixes and any(p.startswith(prefixes) for p in places):
                found.setdefault(sid, "the sensors it used are there")
    # A site under a broader one implies it; Axial's own name in a paper of its vent fields is not needed.
    for child, parent in SITE_PARENT.items():
        if child in found:
            found.setdefault(parent, found[child])
    return sorted(found.items())


def build(output: Path) -> dict:
    links, rec, papers = collect()
    vocabulary = json.loads((Path(__file__).resolve().parent / "vocabulary.json").read_text())
    for e in vocabulary:
        e["rx"] = re.compile(e["pattern"], re.I if e["ignore_case"] else 0)
    by_id = {e["id"]: e for e in vocabulary}
    abstracts, full = defaultdict(str), defaultdict(list)
    for pid, layer, _, _, text in passages():
        if layer == "abstract":
            abstracts[pid] += " " + text
        else:
            full[pid].append(text)

    def site_of_sensor(sid):
        d = rec.get(sid) or {}
        r = next((REFDES.fullmatch(n) for n in [sid, *(d.get("aliases") or [])] if REFDES.fullmatch(n)), None)
        return (r.group(1) if r else None) or d.get("site") or LOCATION_SITE.get(d.get("location") or "")

    # Sensor links, judged.
    judged = {}
    for key, l in links.items():
        if l["target"] not in rec:
            continue
        relation, why, best = judge_sensor(l, papers[l["paper"]], abstracts.get(l["paper"], ""))
        if relation:
            judged[key] = (relation, why, best)
    # A paper that names some sensors of a kind (the Central, Eastern and International District BOTPTs by designator)
    # meant those when it describes the kind in general words: its descriptions do not add the others (ASHES).
    named_kinds = defaultdict(set)
    for (pid, sid), (relation, _, _) in judged.items():
        if links[(pid, sid)]["kinds"] & (CODED | {"system"}) and min((h["share"] or 1) for h in links[(pid, sid)]["hits"]) == 1:
            named_kinds[pid].add(rec[sid].get("instrument_type"))
    for (pid, sid) in list(judged):
        if rec[sid].get("instrument_type") in named_kinds[pid] and links[(pid, sid)]["kinds"] <= {"described"} | ({"system"} if
                min((h["share"] or 1) for h in links[(pid, sid)]["hits"]) > 1 else set()):
            del judged[(pid, sid)]
    used_by_paper = defaultdict(list)
    for (pid, sid), (relation, _, _) in judged.items():
        if relation == "used":
            used_by_paper[pid].append(sid)
    # Papers on RCA data that name no sensor ("ambient seismic noise recorded by the OOI Cabled Array at Axial"): RCA
    # words beside data words in the title or abstract, or in two full-text passages, of a paper that is not an overview.
    def near_data(text):
        return any(USE.search(text[max(0, m.start() - 300): m.end() + 300]) and len(YEARS.findall(text[max(0, m.start() - 300): m.end() + 300])) < 8
                   for m in RCA_WORDS.finditer(text))
    rca_data = {pid for pid, paper in papers.items()
                if (paper.get("publication_year") or 0) >= 2013 and not is_overview(paper.get("title") or "")
                and (near_data(f"{paper.get('title') or ''}. {abstracts.get(pid, '')}") or sum(near_data(t) for t in full.get(pid, [])) >= 2)}

    tmp = output.with_name(output.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    entities, relationships, chunks = [], [], []
    feature_names = {fid: name for fid, name, _, _ in FEATURES}
    site_names = {sid: name for sid, name, _, _ in SITES}

    def link_chunk(pid, target, predicate, text, evidence_chunk=None, page=None):
        paper = papers[pid]
        chunk_id = stable("LINK-", f"{pid}|{target}|{predicate}")
        chunks.append({"chunk_id": chunk_id, "document_id": pid, "entity_ids": [target], "title": paper.get("title"),
                       "text": text, "predicate": predicate, "doi": paper.get("doi"), "source_url": paper.get("source_url"),
                       "evidence_chunk_id": evidence_chunk, "page": page, "source_is_untrusted_data": True,
                       # Fetched only by the paper-link lookups (papers_linked), never by the main search (migration 004).
                       "retrieval_layer": "literature_links"})
        relationships.append({"source_id": chunk_id, "predicate": "EVIDENCE_FOR", "target_id": target})

    def cite(pid):
        p = papers[pid]
        return f"{p.get('title')} ({p.get('publication_year') or 'n.d.'})"

    topic_rows, site_rows, linked_papers = defaultdict(list), defaultdict(list), set()
    for pid, paper in papers.items():
        topic_rows[pid] = paper_topics(pid, paper, abstracts.get(pid, ""), full.get(pid, []), vocabulary)
        site_rows[pid] = paper_sites(paper, abstracts.get(pid, ""), used_by_paper.get(pid, []), site_of_sensor)

    for (pid, sid), (relation, why, best) in sorted(judged.items()):
        l = links[(pid, sid)]
        predicate = "USES_SENSOR" if relation == "used" else "MENTIONS_SENSOR"
        name = rec[sid].get("name") or sid
        relationships.append({"source_id": pid, "predicate": predicate, "target_id": sid, "match": sorted(l["kinds"]),
                              "layers": sorted(l["layers"]), "passages": len(l["passages"]),
                              "passages_about_data": sum(h["use"] for h in l["hits"]), "why": why,
                              "evidence_chunk_id": best["chunk"], "evidence_layer": best["layer"], "evidence_page": best["page"],
                              "sensors_sharing_description": l["shared_with"]})
        verb = "used data from" if relation == "used" else "mentions, without analyzing its data,"
        where = "full text" if best["layer"] == "fulltext" else "abstract"
        link_chunk(pid, sid, predicate,
                   f"{cite(pid)} {verb} {name} ({sid}): {why} (judged from the paper's passages by rule; read the evidence). "
                   f"Evidence ({where}{', page ' + str(best['page']) if best['page'] else ''}): {snippet(best['text'], *best['span'])}",
                   best["chunk"], best["page"])
        linked_papers.add(pid)
    for (pid, fid), l in sorted(links.items()):
        if fid in feature_names:
            relationships.append({"source_id": pid, "predicate": "NAMES_FEATURE", "target_id": fid, "layers": sorted(l["layers"]),
                                  "passages": len(l["passages"]), "evidence_chunk_id": l["evidence_chunk"]})
            link_chunk(pid, fid, "NAMES_FEATURE", f"{cite(pid)} names {feature_names[fid]} in {len(l['passages'])} passage(s). Evidence: {l['evidence']}",
                       l["evidence_chunk"], l["evidence_page"])
            linked_papers.add(pid)
    for pid, rows_ in sorted(topic_rows.items()):
        for t in rows_:
            e = t["entry"]
            predicate = "APPLIES_METHOD" if e["kind"] == "method" else "STUDIES_CONCEPT"
            target = ("METHOD-" if e["kind"] == "method" else "CONCEPT-") + e["id"]
            how = ", ".join(x for x in ["named in its title" if t["in_title"] else "",
                                        f"named {t['abstract_mentions']} time(s) in its abstract" if t["abstract_mentions"] else "",
                                        f"used in {t['fulltext_passages']} full-text passages ({int(t['fulltext_share'] * 100)}%)" if t["fulltext_passages"] else ""] if x)
            relationships.append({"source_id": pid, "predicate": predicate, "target_id": target, "in_title": t["in_title"],
                                  "abstract_mentions": t["abstract_mentions"], "fulltext_passages": t["fulltext_passages"],
                                  "fulltext_share": t["fulltext_share"]})
            verb = "applies the method" if e["kind"] == "method" else "studies"
            link_chunk(pid, target, predicate, f"{cite(pid)} {verb} {e['name']}: {how}. Evidence ({t['evidence_layer']}): {t['evidence']}")
            linked_papers.add(pid)
        title, abstract = papers[pid].get("title") or "", abstracts.get(pid, "")
        site_words = {sid: words for sid, _, words, _ in SITES}
        for site, why in site_rows[pid]:
            # How strongly: the site in the title, then how often the abstract names it (the lookup ranks by these).
            relationships.append({"source_id": pid, "predicate": "ABOUT_SITE", "target_id": site, "why": why,
                                  "in_title": bool(re.search(site_words[site], title)),
                                  "abstract_mentions": len(re.findall(site_words[site], abstract))})
            link_chunk(pid, site, "ABOUT_SITE", f"{cite(pid)} is about {site_names[site]}: {why}.")
            linked_papers.add(pid)

    # Nodes: papers (with what they link to, so one lookup returns a paper's methods beside its sensor link), sensors,
    # features, methods, concepts and sites.
    for pid in sorted(linked_papers):
        d = papers[pid]
        entities.append({"entity_id": pid, "entity_type": "paper", "name": d.get("title") or pid, "doi": d.get("doi"),
                         "publication_year": d.get("publication_year"), "citation": d.get("citation"), "source_url": d.get("source_url"),
                         "uses_rca_data": bool(used_by_paper.get(pid)) or pid in rca_data,
                         "sensors_used": sorted(used_by_paper.get(pid, [])),
                         "methods": [t["entry"]["name"] for t in topic_rows[pid] if t["entry"]["kind"] == "method"],
                         "concepts": [t["entry"]["name"] for t in topic_rows[pid] if t["entry"]["kind"] == "concept"],
                         "sites": [site_names[s] for s, _ in site_rows[pid]]})
    for sid in sorted({sid for _, sid in judged}):
        d = rec[sid]
        codes = [m.group(1) for m in [re.fullmatch(r"EARTHSCOPE-OO-([A-Z0-9]+)", sid)] if m]
        entities.append({"entity_id": sid, "entity_type": "sensor", "name": d.get("name") or sid, "canonical_id": sid,
                         "aliases": sorted({*(d.get("aliases") or []), *codes, d.get("instrument_id") or sid}),
                         "instrument_type": d.get("instrument_type"), "location": d.get("location")})
    for fid in sorted({fid for _, fid in links if fid in feature_names}):
        entities.append({"entity_id": fid, "entity_type": "feature", "name": feature_names[fid]})
    for e in vocabulary:
        target = ("METHOD-" if e["kind"] == "method" else "CONCEPT-") + e["id"]
        parent = e.get("parent") and ("METHOD-" if e["kind"] == "method" else "CONCEPT-") + e["parent"]
        entities.append({"entity_id": target, "entity_type": e["kind"], "name": e["name"], "aliases": [e["id"]],
                         "group": e["group"], "definition": e["definition"], "parent": parent})
        if parent:
            relationships.append({"source_id": target, "predicate": "NARROWER_THAN", "target_id": parent})
    for sid, name, _, _ in SITES:
        entities.append({"entity_id": sid, "entity_type": "site", "name": name, "aliases": [sid.removeprefix("SITE-")],
                         "parent": SITE_PARENT.get(sid)})
        if sid in SITE_PARENT:
            relationships.append({"source_id": sid, "predicate": "NARROWER_THAN", "target_id": SITE_PARENT[sid]})

    def write(name, rows_):
        (tmp / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_), encoding="utf-8")

    write("entities.jsonl", entities)
    write("chunks.jsonl", chunks)
    write("relationships.jsonl", relationships)
    by_pred = defaultdict(int)
    for r in relationships:
        by_pred[r["predicate"]] += 1
    manifest = {
        "schema_version": "2.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Links from literature papers to the RCA sensors they used or mention, the methods they apply, the concepts "
                 "they study, the sites they are about and the features they name, from abstracts and full text",
        "embedding_input": "chunks.jsonl", "graph_node_inputs": ["entities.jsonl", "chunks.jsonl"],
        "graph_edge_input": "relationships.jsonl",
        "counts": {"papers": len(linked_papers), "sensors": len({sid for _, sid in judged}),
                   "papers_using_rca_data": len({p for p, v in used_by_paper.items() if v} | rca_data),
                   "papers_naming_the_sensors_they_used": sum(1 for v in used_by_paper.values() if v), **dict(by_pred)},
        "limitations": [
            "Every link is judged by rule from the paper's passages, not read by a person: USES_SENSOR when passages naming the "
            "sensor talk about its data (or an abstract names it), MENTIONS_SENSOR otherwise; each link keeps its evidence passage.",
            "A sensor described only by its site and kind is linked when the description is specific; several sensors alike "
            "at a site share it (the count is kept).",
            "APPLIES_METHOD and STUDIES_CONCEPT come from the vocabulary's words in a paper's title, abstract or many of its "
            "full-text passages; entries papers name as their setting need more. ABOUT_SITE: a site named in the title or "
            "abstract, or where the sensors the paper used are.",
        ],
        "validation_status": "pass",
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.rmtree(output, ignore_errors=True)
    tmp.rename(output)
    return manifest


WORKER_TERMS = ROOT / "src/atlas_worker/src/link_terms.json"


def worker_terms() -> list[dict]:
    """The methods, concepts and sites as the Worker matches a question against them (the same words as the build)."""
    vocabulary = json.loads((Path(__file__).resolve().parent / "vocabulary.json").read_text())
    terms = [{"id": ("METHOD-" if e["kind"] == "method" else "CONCEPT-") + e["id"], "kind": e["kind"], "name": e["name"],
              "pattern": e["pattern"], "flags": "i" if e["ignore_case"] else "",
              "parent": e["parent"] and ("METHOD-" if e["kind"] == "method" else "CONCEPT-") + e["parent"]} for e in vocabulary]
    terms += [{"id": sid, "kind": "site", "name": name, "pattern": words, "flags": "i", "parent": SITE_PARENT.get(sid)}
              for sid, name, words, _ in SITES]
    return terms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--terms-only", action="store_true", help="Only write the Worker's copy of the terms.")
    args = parser.parse_args()
    WORKER_TERMS.write_text(json.dumps(worker_terms(), indent=1, ensure_ascii=False) + "\n")
    if not args.terms_only:
        print(json.dumps(build(args.output)["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
