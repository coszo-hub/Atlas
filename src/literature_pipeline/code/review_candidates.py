#!/usr/bin/env python3
"""Merge the discovery searches into one review list of papers the catalog does not have, in tiers.

Reads discover_openalex.py's and discover_papers.py's reports, keeps one row per DOI (else OpenAlex ID), and grades
each by the strongest evidence any search found:

1 uses_rca     from 2009 (NEPTUNE's pilot) on: its title or abstract names the RCA or OOI with an RCA place, or its full
               text names an OO station, a site designator or the cabled array, corroborated by a second such hit, an
               RCA place or name in its title or abstract, or a citation of an RCA paper
2 rca_place    its title or abstract names an RCA site or feature (Axial Seamount, Hydrate Ridge, Slope Base, ASHES ...)
3 text_place   only its full text names an RCA place (with Cascadia or the Juan de Fuca Ridge)
4 citation     found only by citing RCA papers

5 meeting_abstract  a conference abstract with tier-1 evidence (AGU, OCEANS ...)

Datasets, errata, editorials and other non-papers are kept apart (tier "not_a_paper").
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAPER_TYPES = {"article", "journal-article", "preprint", "posted-content", "dissertation", "book-chapter", "book",
               "conference-paper", "proceedings-article", "report", "review", "monograph", "other"}
# Case-sensitive: "ashes", "slope base" and "RCA" (a coronary artery) are not the RCA's.
RCA_NAME = re.compile(r"Regional Cabled Array|[Cc]abled [Aa]rray|Cabled Axial|Ocean Observatories Initiative|\bOOI\b|NEPTUNE|"
                      r"\b(AXAS[12]|AXBA1|AXCC[12]|AXEC[123]|AXID1|HYS1[1-4]|HYSB1|CZ(MID|OFF|OSH|SHF))\b|\b(RS0[13]|CE0[24])[A-Z0-9]{4}\b")
PLACE = re.compile(r"Axial ([Ss]eamount|[Vv]olcano|[Cc]aldera)|Hydrate Ridge|Endurance Array|CoAxial")
# Names that are RCA places only beside Axial, Oregon or Cascadia.
PLACE_IF = re.compile(r"\bASHES\b|International District|Slope Base")
CONTEXT = re.compile(r"Axial|Oregon|Cascadia|Juan de Fuca")
# Searches whose hit means the full text names the RCA: station codes, site designators, the array's own names.
STRONG = ("code:", "site:", 'name:"Regional Cabled Array"', 'name:"Cabled Axial Seamount"', 'name:"OOI cabled array"',
          "rca+kind:", "ooi+place:", "fulltext:")
FULLTEXT_PLACE = ("sitename:", "feature:", "place+topic:")


def rca_place(text: str) -> bool:
    return bool(PLACE.search(text) or (PLACE_IF.search(text) and CONTEXT.search(text)))


def tier(row: dict) -> str:
    """See the module docstring; one full-text hit alone (a station code is also a gene or a sample label) is not enough."""
    labels = row["found_by"]
    text = f"{row.get('title') or ''} {row.get('abstract') or ''}"
    year = row.get("year") or 0
    # Independent kinds of evidence: station codes and designators count once (AXEC1 and AXEC2 together are also gene
    # names), the array's names in full text, OOI with an RCA place in full text, and the title or abstract.
    families = set()
    if any(l.startswith(("code:", "site:")) or re.match(r"fulltext:[A-Z]{2}\w*\d", l) for l in labels):
        families.add("code")
    if any(l.startswith(('name:"Regional Cabled Array"', 'name:"Cabled Axial Seamount"', 'name:"OOI cabled array"', "rca+kind:"))
           or l.startswith("fulltext:Regional Cabled Array") for l in labels):
        families.add("name")
    if any(l.startswith(("ooi+place:", "fulltext:Ocean Observatories Initiative+", "fulltext:OOI+")) for l in labels):
        families.add("ooi_place")
    place = rca_place(text)
    if place or RCA_NAME.search(text):
        families.add("text")
    if any(l.startswith(("cites", "cites-catalog")) for l in labels):
        families.add("cites")
    place_search = any(l.startswith(FULLTEXT_PLACE) for l in labels)
    by_text = bool(RCA_NAME.search(text)) and place
    strong = families & {"code", "name", "ooi_place"}
    uses = year >= 2009 and (by_text or (strong and len(families) >= 2))
    kind = row.get("type") or ""
    if kind == "conference-abstract":
        return "5_meeting_abstract" if uses else "not_a_paper"
    if kind not in PAPER_TYPES:
        return "not_a_paper"
    if uses:
        return "1_uses_rca"
    if place:
        return "2_rca_place"
    if strong or place_search:
        return "3_text_place"
    return "4_citation"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openalex", type=Path, required=True)
    parser.add_argument("--keyless", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/Literature/literature.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    works = [json.loads(l) for l in args.catalog.read_text(encoding="utf-8").splitlines() if l.strip()]
    norm = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())
    have_doi = {(w.get("resolved_doi") or "").lower() for w in works} - {""}
    have_title = {norm(w.get("resolved_title")) for w in works} - {""}
    merged: dict[str, dict] = {}
    for path in (args.openalex, args.keyless):
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            key = (r.get("doi") or "").lower() or r.get("openalex_id")
            if not key or key in have_doi or norm(r.get("title")) in have_title:
                continue
            labels = [l for l in r.get("found_by", []) if not l.startswith("+")]
            if key in merged:
                m = merged[key]
                m["found_by"] = m["found_by"] + [l for l in labels if l not in m["found_by"]]
                for k in ("abstract", "venue", "first_author", "openalex_id"):
                    if not m.get(k) and r.get(k):
                        m[k] = r[k]
            else:
                merged[key] = {"key": key, "doi": r.get("doi"), "openalex_id": r.get("openalex_id"), "title": r.get("title"),
                               "year": r.get("year"), "type": r.get("type"), "venue": r.get("venue"),
                               "first_author": r.get("first_author"), "abstract": r.get("abstract") or "", "found_by": labels}
    rows = list(merged.values())
    for r in rows:
        r["tier"] = tier(r)
        r["found_by_count"] = len(r["found_by"])
    rows.sort(key=lambda r: (r["tier"], -r["found_by_count"], -(r["year"] or 0)))
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(json.dumps({"candidates": len(rows), **dict(sorted(Counter(r["tier"] for r in rows).items()))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
