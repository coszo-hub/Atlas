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
REFDES = re.compile(r"\b((?:RS|CE)\d\d[A-Z0-9]{4})-([A-Z0-9]{5})-(?:(\d\d)-)?([A-Z0-9]{9})\b")
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
    ("PREST", r"\bPRESTs?\b|[Tt]idal (?:[Ss]eafloor )?[Pp]ressure|SBE ?54", _model("PREST", "Tidal"), None, True),
    ("HPIES", r"\bHPIES\b", _model("HPIES"), None, False),
    ("OsmoSampler", r"[Oo]smo ?[Ss]amplers?|osmotic (?:fluid )?sampler", _model("OsmoSampler", "Osmotic"), None, True),
    ("mass spectrometer", r"[Mm]ass [Ss]pectrometers?|\bMASSP\b", _model("Mass Spec"), None, True),
    ("RAS", r"\bRAS\b|[Rr]emote [Aa]ccess (?:[Ff]luid )?[Ss]ampler", _model("Remote Access Fluid", "RASFL"), r"International District|Axial", True),
    ("MARUM sonars", r"[Oo]verview [Ss]onar|\bSHROS\b|[Rr]otary [Ss]onar", _model("Overview Sonar", "Rotary Sonar"), r"Hydrate Ridge|\bSHR\b", True),
    ("MARUM camera", r"MARUM (?:camera|video)|pan[- ]tilt camera", _model("MARUM Camera"), r"Hydrate Ridge|\bSHR\b", True),
    ("echosounder", r"\bZPLSC\b|EK-?60|[Bb]io-?acoustic [Ss]onar", _model("ZPLSC", "EK-60"), r"Endurance|Oregon", True),
    ("FETCH", r"\bFETCH\b|[Aa]coustic (?:ranging|extensometer|transponders?)", _model("FETCH", "Acoustic Transponders"), r"Axial|caldera", True),
    ("strainmeter", r"(?:[Ss]eafloor|[Oo]ptical[- ]fib(?:er|re)) strainmeters?|[Oo]ptical[- ]fib(?:er|re) strain", _model("STRAINMETER"), r"Oregon|Cascadia|Slope Base|Hydrate Ridge", False),
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
DAS_BY = [(r"multi-?span|repeaters?|Nokia|2025", ("PI-DAS25",)), (r"OptoDAS|RAPID|2024", ("PI-DAS24",)),
          (r"OptaSense(?!.*2021)", ("PI-DAS-OPTASENSE",)), (r"2021|community|QuantX|DTS|.", ("RCA-DAS-2021-COMMUNITY-TEST",))]

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


def build(output: Path) -> dict:
    rec, by_code, by_refdes, by_site = sensors()
    papers = {d["document_id"]: d for d in read_jsonl(LIT / "documents.jsonl")}
    site_rx = {s: (re.compile(rf"{p}|\b{s}\b"), axial) for s, (p, axial) in SITE_NAMES.items()}
    site_rx.update({place: (re.compile(rf"\b{place[5:]}\b"), False) for place in by_site if place.startswith("NODE:")})
    kind_rx = {k: re.compile(p) for k, p in KIND_WORDS.items()}
    feat_rx = [(fid, name, re.compile(p), axial) for fid, name, p, axial in FEATURES]

    # Which papers name the RCA anywhere (the condition for a description to count).
    rca_paper = set()
    rows = list(passages())
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
                                      "evidence": None, "evidence_rank": 9, "shared_with": None})
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
        for name, rx, ids, needs, rca_only in systems:
            m = rx.search(text)
            if not m or (needs and not needs.search(text)) or (rca_only and pid not in rca_paper):
                continue
            if name == "DAS":
                for words, chosen in DAS_BY:
                    if re.search(words, text):
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
                for i in ids:
                    add(pid, i, "described", layer, cid, page, text, m.span(), share=len(ids))
        year = papers[pid].get("publication_year") or 0
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

    # The graph: papers, sensors and features as nodes; links as edges; one evidence passage a link.
    tmp = output.with_name(output.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    used_papers = {l["paper"] for l in links.values()}
    used_targets = {l["target"] for l in links.values()}
    entities = []
    for pid in sorted(used_papers):
        d = papers[pid]
        entities.append({"entity_id": pid, "entity_type": "paper", "name": d.get("title") or pid, "doi": d.get("doi"),
                         "publication_year": d.get("publication_year"), "citation": d.get("citation"), "source_url": d.get("source_url")})
    for sid in sorted(t for t in used_targets if t in rec):
        d = rec[sid]
        codes = [m.group(1) for m in [re.fullmatch(r"EARTHSCOPE-OO-([A-Z0-9]+)", sid)] if m]
        entities.append({"entity_id": sid, "entity_type": "sensor", "name": d.get("name") or sid, "canonical_id": sid,
                         "aliases": sorted({*(d.get("aliases") or []), *codes, d.get("instrument_id") or sid}),
                         "instrument_type": d.get("instrument_type"), "location": d.get("location")})
    feature_names = {fid: name for fid, name, _, _ in FEATURES}
    for fid in sorted(t for t in used_targets if t in feature_names):
        entities.append({"entity_id": fid, "entity_type": "feature", "name": feature_names[fid]})

    relationships, chunks = [], []
    for (pid, target), l in sorted(links.items()):
        is_sensor = target in rec
        how = sorted(l["kinds"])
        predicate = ("NAMES_SENSOR" if set(how) & {"named", "range", "designator", "system"} else "DESCRIBES_SENSOR") if is_sensor else "NAMES_FEATURE"
        target_name = rec[target].get("name") if is_sensor else feature_names[target]
        paper = papers[pid]
        chunk_id = stable("LINK-", f"{pid}|{target}")
        relationships.append({"source_id": pid, "predicate": predicate, "target_id": target, "match": how,
                              "layers": sorted(l["layers"]), "passages": len(l["passages"]), "evidence_chunk_id": l["evidence_chunk"],
                              "evidence_layer": l["evidence_layer"], "evidence_page": l["evidence_page"],
                              "sensors_sharing_description": l["shared_with"]})
        verb = {"NAMES_SENSOR": "names", "DESCRIBES_SENSOR": "describes", "NAMES_FEATURE": "names"}[predicate]
        text = (f"{paper.get('title')} ({paper.get('publication_year') or 'n.d.'}) {verb} {target_name}"
                + (f" ({target})" if is_sensor else "") + f" in {len(l['passages'])} passage(s) of its "
                + " and ".join("full text" if x == "fulltext" else "abstract" for x in sorted(l["layers"])) + ". Evidence: " + l["evidence"])
        chunks.append({"chunk_id": chunk_id, "document_id": pid, "entity_ids": [target], "title": paper.get("title"),
                       "text": text, "predicate": predicate, "doi": paper.get("doi"), "source_url": paper.get("source_url"),
                       "evidence_chunk_id": l["evidence_chunk"], "page": l["evidence_page"], "source_is_untrusted_data": True,
                       # Fetched only by the papers lookup (papers_linked), never by the main search (migration 004).
                       "retrieval_layer": "literature_links"})
        relationships.append({"source_id": chunk_id, "predicate": "EVIDENCE_FOR", "target_id": target})

    def write(name, rows_):
        (tmp / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_), encoding="utf-8")

    write("entities.jsonl", entities)
    write("chunks.jsonl", chunks)
    write("relationships.jsonl", relationships)
    by_pred = defaultdict(int)
    for r in relationships:
        by_pred[r["predicate"]] += 1
    manifest = {
        "schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Links from literature papers to the RCA sensors and features they name or describe, from abstracts and full text",
        "embedding_input": "chunks.jsonl", "graph_node_inputs": ["entities.jsonl", "chunks.jsonl"],
        "graph_edge_input": "relationships.jsonl",
        "counts": {"papers": len(used_papers), "sensors": sum(t in rec for t in used_targets),
                   "features": sum(t in feature_names for t in used_targets), "links": len(links), **dict(by_pred)},
        "limitations": [
            "NAMES_SENSOR links are literal station codes, station ranges or reference designators.",
            "DESCRIBES_SENSOR links match a site name and a kind of instrument in one passage of a 2009-or-later paper that names "
            "the RCA, OOI or a station; when several sensors of that kind share the site, each is linked and the count is kept.",
            "Links say a paper names or describes a sensor, not that it used the sensor's data; the evidence passage shows which.",
        ],
        "validation_status": "pass",
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.rmtree(output, ignore_errors=True)
    tmp.rename(output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output)["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
