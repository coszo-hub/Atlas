#!/usr/bin/env python3
"""Candidate papers for each sensor's "which papers used / mention it" gold, with the passages to judge them by.

Wider than the literature links on purpose (the gold must not be the links checked against themselves): a paper is a
candidate if any abstract or full-text passage names the sensor (station code, designator, system name), or if the
paper as a whole names the sensor's site, its kind of instrument and the RCA or OOI, from 2009 on. For each candidate
the best passages are kept (those naming the sensor, then those with its site and kind close together), for a person
to judge used (in the paper's own methods or analysis), mentioned, or not about it.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RCA = re.compile(r"Regional Cabled Array|[Cc]abled [Aa]rray|Ocean Observatories Initiative|\bOOI\b|\bRSN\b|NEPTUNE")

# sensor -> (names that identify it, site words, kind words); names are case-sensitive codes and system names.
SENSORS = {
    "EARTHSCOPE-OO-HYSB1": (r"\bHYSB1\b", r"Slope Base", r"seismomet|\bOBSs?\b"),
    "EARTHSCOPE-OO-AXCC1": (r"\bAXCC1\b", r"Central Caldera|caldera cent", r"seismomet|\bOBSs?\b"),
    "EARTHSCOPE-OO-AXEC2": (r"\bAXEC2\b", r"Eastern Caldera|eastern (?:wall|rim|side) of the caldera", r"seismomet|\bOBSs?\b"),
    "EARTHSCOPE-OO-AXBA1": (r"\bAXBA1\b", r"Axial Base|base of Axial", r"seismomet|\bOBSs?\b"),
    "EARTHSCOPE-OO-AXAS1": (r"\bAXAS1\b", r"\bASHES\b", r"seismomet|\bOBSs?\b"),
    "EARTHSCOPE-OO-AXID1": (r"\bAXID1\b", r"International District", r"seismomet|\bOBSs?\b"),
    "EARTHSCOPE-OO-HYS11": (r"\bHYS11\b|HYS11\s*[-‐–—]\s*1?[234]", r"Southern Hydrate Ridge|Hydrate Ridge summit|\bSHR\b", r"seismomet|\bOBSs?\b"),
    "EARTHSCOPE-OO-AXEC3": (r"\bAXEC3\b|AXEC1\s*[-‐–—]\s*(?:AXEC)?3", r"Eastern Caldera", r"seismomet|\bOBSs?\b"),
    "RS03CCAL-MJ03F-05-BOTPTA301": (r"RS03CCAL-MJ03F(?:-05)?-BOTPT|\bMJ03F\b", r"Central Caldera|caldera cent", r"BOTPT|bottom pressure|pressure[- ]tilt|BPR|tilt"),
    "RS03ECAL-MJ03E-06-BOTPTA302": (r"RS03ECAL-MJ03E(?:-06)?-BOTPT|\bMJ03E\b", r"Eastern Caldera", r"BOTPT|bottom pressure|pressure[- ]tilt|BPR|tilt"),
    "RS03INT2-MJ03D-06-BOTPTA303": (r"RS03INT2-MJ03D(?:-06)?-BOTPT|\bMJ03D\b", r"International District", r"BOTPT|bottom pressure|pressure[- ]tilt|BPR|tilt"),
    "RS03ASHS-MJ03B-09-BOTPTA304": (r"RS03ASHS-MJ03B(?:-09)?-BOTPT|\bMJ03B\b", r"\bASHES\b", r"BOTPT|bottom pressure|pressure[- ]tilt|BPR|tilt"),
    "RS01SLBS-MJ01A-06-PRESTA101": (r"RS01SLBS-MJ01A(?:-06)?-PREST|\bPRESTA101\b", r"Slope Base", r"PREST|tidal pressure|pressure (?:sensor|gauge)|SBE ?54|bottom pressure"),
    "RS03AXBS-MJ03A-06-PRESTA301": (r"RS03AXBS-MJ03A(?:-06)?-PREST|\bPRESTA301\b", r"Axial Base|base of Axial", r"PREST|tidal pressure|pressure (?:sensor|gauge)|SBE ?54|bottom pressure"),
    "RS01SUM1-LJ01B-09-PRESTB102": (r"RS01SUM1-LJ01B(?:-09)?-PREST|\bPRESTB102\b", r"Hydrate Ridge", r"PREST|tidal pressure|pressure (?:sensor|gauge)|SBE ?54|bottom pressure"),
    "SCPRAAA301": (r"\bSCPRs?\b|[Ss]elf[- ][Cc]alibrating [Pp]ressure [Rr]ecorder", r"Axial|Central Caldera", r"pressure"),
    "AOABPA301": (r"\bA-0-A\b|ambient[- ]zero[- ]ambient", r"Axial|Central Caldera", r"pressure"),
    "PI-COVIS": (r"\bCOVIS\b|Cabled Observatory Vent Imaging Sonar", r"\bASHES\b", r"sonar"),
    "RS03ASHS-PN03B-06-CAMHDA301": (r"\bCam ?HD\b|CAMHDA301", r"\bASHES\b|Mushroom", r"HD (?:video )?camera|high[- ]definition camera"),
    "PI-QNTSRA101": (r"[Rr]otary [Ss]onar|QNTSRA101", r"Hydrate Ridge|\bSHR\b", r"sonar"),
    "PI-OVRSRA101": (r"[Oo]verview [Ss]onar|\bSHROS\b|OVRSRA101", r"Hydrate Ridge|\bSHR\b", r"sonar"),
    "RS01SUM2-MJ01B-06-MASSPA101": (r"MASSPA101|RS01SUM2-MJ01B(?:-06)?-MASSP", r"Hydrate Ridge|\bSHR\b", r"[Mm]ass [Ss]pectrometer"),
    "RS03INT1-MJ03C-06-MASSPA301": (r"MASSPA301|RS03INT1-MJ03C(?:-06)?-MASSP", r"International District", r"[Mm]ass [Ss]pectrometer"),
    "RS03ASHS-MJ03B-00-OSMOIA301": (r"OSMOIA301", r"\bASHES\b", r"[Oo]smo ?[Ss]ampler|osmotic"),
    "RS03INT1-MJ03C-07-RASFLA301": (r"RASFLA301|[Rr]emote [Aa]ccess (?:[Ff]luid )?[Ss]ampler", r"International District", r"\bRAS\b|fluid sampler"),
    "RS03AXBS-LJ03A-05-HPIESA301": (r"HPIESA301", r"Axial Base|base of Axial|Axial", r"\bHPIES\b|inverted echo sounder"),
    "RS01SLBS-LJ01A-05-HPIESA101": (r"HPIESA101", r"Slope Base", r"\bHPIES\b|inverted echo sounder"),
    "RS03CCAL-MJ03F-08-FETCHA301": (r"\bFETCH\b|FETCHA301", r"Axial|caldera", r"acoustic (?:ranging|extensometer|transponder)|horizontal (?:deformation|extension)"),
    "RCA-DAS-2021-COMMUNITY-TEST": (r"(?:DAS|distributed acoustic sensing).{0,200}(?:OOI|Regional Cabled Array|RCA)|(?:OOI|Regional Cabled Array|RCA).{0,200}(?:DAS|distributed acoustic sensing)", r"Oregon|Newport|Pacific City", r"\bDAS\b|distributed acoustic"),
    "PI-DAS25": (r"[Mm]ulti-?span|beyond (?:optical )?repeaters?|Nokia", r"Oregon|RCA|OOI", r"\bDAS\b|distributed acoustic"),
    "COSZO-STRAINMETER-EW": (r"(?:seafloor|optical[- ]fib(?:er|re)) strainmeters?|optical[- ]fib(?:er|re) strain", r"Slope Base|Oregon|Cascadia|Hydrate Ridge", r"strainmeter|strain"),
    "CE04OSPS-PC01B-05-ZPLSCB102": (r"\bZPLSC|EK-?60", r"Oregon Offshore|Endurance|Oregon", r"echo ?sounder|bio-?acoustic|EK-?60"),
    "RS01SLBS-LJ01A-09-HYDBBA102": (r"HYDBBA102|RS01SLBS-LJ01A(?:-09)?-HYDBB", r"Slope Base", r"broadband hydrophone|hydrophone"),
    "RS03AXBS-LJ03A-09-HYDBBA302": (r"HYDBBA302|RS03AXBS-LJ03A(?:-09)?-HYDBB", r"Axial Base|base of Axial", r"broadband hydrophone|hydrophone"),
    "CE02SHBP-LJ01D-11-HYDBBA106": (r"HYDBBA106|CE02SHBP-LJ01D(?:-11)?-HYDBB", r"Oregon Shelf|Oregon shelf", r"broadband hydrophone|hydrophone"),
    "RS03CCAL-MJ03F-06-HYDLFA305": (r"HYDLFA305|RS03CCAL-MJ03F(?:-06)?-HYDLF", r"Central Caldera|caldera", r"low[- ]frequency hydrophone|hydrophone"),
    "RS01SLBS-MJ01A-05-HYDLFA101": (r"HYDLFA101|RS01SLBS-MJ01A(?:-05)?-HYDLF", r"Slope Base", r"low[- ]frequency hydrophone|hydrophone"),
}
NEAR = 400


def snippet(text, start, end, width=230):
    a, b = max(0, start - width), min(len(text), end + width)
    return ("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    docs = {json.loads(l)["document_id"]: json.loads(l) for l in (ROOT / "data/Literature/documents.jsonl").read_text().splitlines() if l.strip()}
    passages = defaultdict(list)
    for line in (ROOT / "data/Literature/chunks.jsonl").read_text().splitlines():
        c = json.loads(line)
        if c.get("document_type") == "literature_work":
            passages[c["document_id"]].append(("abstract", c.get("text") or ""))
    for line in (ROOT / "data/LiteratureFullText/chunks.jsonl").read_text().splitlines():
        c = json.loads(line)
        passages[c["document_id"]].append((f"p{c.get('page') or '?'}", c.get("text") or ""))
    out = {}
    for sid, (names, site, kind) in SENSORS.items():
        n_rx, s_rx, k_rx = re.compile(names, re.S), re.compile(site, re.I), re.compile(kind, re.I)
        cands = []
        for pid, ps in passages.items():
            if pid not in docs:
                continue
            whole = " ".join(t for _, t in ps)
            year = docs[pid].get("publication_year") or 0
            named = [(where, m) for where, t in ps for m in [n_rx.search(t)] if m]
            co = year >= 2009 and s_rx.search(whole) and k_rx.search(whole) and RCA.search(whole)
            if not (named or co):
                continue
            evidence = []
            for where, t in ps:
                m = n_rx.search(t)
                if m:
                    evidence.append((0, where, snippet(t, *m.span())))
            for where, t in ps:
                for sm in s_rx.finditer(t):
                    window = t[max(0, sm.start() - NEAR): sm.end() + NEAR]
                    if k_rx.search(window):
                        evidence.append((1, where, snippet(t, max(0, sm.start() - 150), sm.end() + 150)))
                        break
            near = any(rank == 1 for rank, _, _ in evidence)
            if not (named or near):
                continue   # site, kind and the RCA only somewhere in the paper, never together
            seen, best = set(), []
            for rank, where, s in sorted(evidence, key=lambda e: e[0]):
                if s not in seen and len(best) < 3:
                    seen.add(s)
                    best.append(f"[{where}] {s}")
            cands.append({"paper": pid, "year": year, "title": docs[pid].get("title"), "named": bool(named),
                          "named_in": sorted({w for w, _ in named})[:6], "evidence": best})
        cands.sort(key=lambda c: (not c["named"], -(c["year"] or 0)))
        out[sid] = cands
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(json.dumps({s: (len(c), sum(x["named"] for x in c)) for s, c in out.items()}, indent=0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
