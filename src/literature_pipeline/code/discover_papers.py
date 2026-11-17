#!/usr/bin/env python3
"""Find papers about the RCA's instruments, sites and features that the catalog does not have, from keyless sources.

Three free sources, none needing an API key:
- Europe PMC full-text search, for every OO station code and RCA/Endurance site designator on the map, and the RCA's
  names with its places (open-access full text; mostly biomedical journals, but Science Advances, PLOS, Frontiers, ...);
- Crossref title and abstract search, for the RCA's names with its places, instruments and features;
- OpenCitations, for the works citing the RCA's foundational papers and the RCA papers the catalog already has.

Each candidate not in the catalog (by DOI) is looked up in Crossref for its title, abstract, type and venue, and graded
by what names the RCA: "strong" when its full text names a station, designator or the Regional Cabled Array, or its
title or abstract names the RCA or OOI with an RCA place; "place" when its title or abstract names an RCA place or
feature only; "citation" when it was found only by citing an RCA paper. Responses are cached so a rerun resumes. The
review list goes to --report; nothing is added to the catalog here (add_doi_papers.py does that, after review).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[3]
CODES = ["AXAS1", "AXAS2", "AXBA1", "AXCC1", "AXCC2", "AXEC1", "AXEC2", "AXEC3", "AXID1", "HYS11", "HYS12", "HYS13",
         "HYS14", "HYSB1", "CZMID", "CZOFF", "CZOSH", "CZSHF"]
SITES = ["CE02SHBP", "CE04OSBP", "CE04OSPD", "CE04OSPS", "RS01SBPD", "RS01SBPS", "RS01SLBS", "RS01SUM1", "RS01SUM2",
         "RS03ASHS", "RS03AXBS", "RS03AXPD", "RS03AXPS", "RS03CCAL", "RS03ECAL", "RS03INT1", "RS03INT2"]
PLACES = ["Axial Seamount", "Axial Volcano", "Hydrate Ridge", "Slope Base", "Endurance Array", "Oregon shelf",
          "ASHES vent field", "International District", "Axial caldera", "Cascadia margin Oregon"]
NAMES = ["Regional Cabled Array", "Ocean Observatories Initiative", "OOI cabled", "cabled observatory", "NEPTUNE"]
TOPICS = ["seismometer", "hydrophone", "seafloor pressure", "tilt", "BOTPT", "COVIS", "shallow profiler", "deep profiler",
          "CTD", "camera", "mass spectrometer", "methane seep", "hydrothermal vent", "eruption", "earthquakes",
          "distributed acoustic sensing", "geodesy", "fin whale", "ambient noise", "dissolved oxygen", "upwelling"]
FOUNDATIONAL = ["10.1016/j.margeo.2014.03.010", "10.3389/fmars.2019.00074", "10.1126/science.aah5563",
                "10.1126/science.aah4666", "10.1126/science.aah4529", "10.5670/oceanog.2018.111", "10.5670/oceanog.2018.123"]
RCA = re.compile(r"Regional Cabled Array|cabled array|Cabled Axial|cabled observator|Ocean Observatories Initiative|\bOOI\b|"
                 r"\bRCA\b|NEPTUNE|" + "|".join(CODES + SITES), re.I)
PLACE = re.compile(r"Axial (Seamount|Volcano|caldera)|Hydrate Ridge|Slope Base|ASHES|International District|"
                   r"Endurance Array|Juan de Fuca|Cascadia|Oregon (shelf|slope|margin|coast)|Newport", re.I)
SKIP_TYPES = {"component", "peer-review", "dataset", "journal-issue", "journal", "grant", "standard"}


class Fetch:
    """GET with a cache keyed by URL and parameters, and polite pacing and retries."""

    def __init__(self, cache: Path):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(timeout=90, headers={"User-Agent": "RCA-Atlas/1.0"}, follow_redirects=True)

    def json(self, url: str, params: dict | None = None, pause: float = 0.25):
        key = hashlib.sha256((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()[:24]
        saved = self.cache / f"{key}.json"
        if saved.exists():
            return json.loads(saved.read_text())
        for attempt in range(5):
            r = self.client.get(url, params=params)
            if r.status_code == 200:
                break
            if r.status_code == 404:
                saved.write_text("null")
                return None
            time.sleep(2 ** attempt * 2)
        r.raise_for_status()
        time.sleep(pause)
        body = r.json()
        saved.write_text(json.dumps(body))
        return body


def europepmc(f: Fetch, query: str, cap: int = 1000) -> list[str]:
    dois, cursor = [], "*"
    while cursor and len(dois) < cap:
        body = f.json("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                      {"query": query, "format": "json", "pageSize": 1000, "cursorMark": cursor, "resultType": "lite"})
        rows = body.get("resultList", {}).get("result", [])
        dois += [r["doi"].lower() for r in rows if r.get("doi")]
        nxt = body.get("nextCursorMark")
        cursor = nxt if rows and nxt != cursor else None
    return dois


def crossref_search(f: Fetch, query: str, rows: int = 400) -> list[str]:
    body = f.json("https://api.crossref.org/works", {"query.bibliographic": query, "rows": rows, "select": "DOI,score"})
    return [i["DOI"].lower() for i in body["message"]["items"]]


def citing(f: Fetch, doi: str) -> list[str]:
    body = f.json(f"https://api.opencitations.net/index/v2/citations/doi:{doi}", pause=0.4) or []
    out = []
    for row in body:
        m = re.search(r"\bdoi:(\S+)", row.get("citing", ""))
        if m:
            out.append(m.group(1).lower())
    return out


def crossref_work(f: Fetch, doi: str) -> dict | None:
    body = f.json(f"https://api.crossref.org/works/{quote(doi, safe='')}", pause=0.15)
    return body and body.get("message")


def openalex_key() -> str | None:
    import os
    if os.environ.get("OPENALEX_API_KEY"):
        return os.environ["OPENALEX_API_KEY"]
    env = ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("OPENALEX_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def inverted(inv: dict | None) -> str:
    return " ".join(w for _, w in sorted((p, w) for w, ps in (inv or {}).items() for p in ps))


def lookup(f: Fetch, dois: list[str]) -> dict[str, dict]:
    """Title, abstract, type, venue, year and first author: from OpenAlex 50 DOIs a request when there is a key
    (one Crossref request per DOI otherwise, and for any DOI OpenAlex does not have)."""
    out, key = {}, openalex_key()
    if key:
        for i in range(0, len(dois), 50):
            batch = dois[i:i + 50]
            body = f.json("https://api.openalex.org/works", {"filter": "doi:" + "|".join(batch), "per-page": 50, "api_key": key,
                          "select": "doi,title,publication_year,type,primary_location,abstract_inverted_index,authorships"}, pause=0.1)
            for w in (body or {}).get("results", []):
                d = (w.get("doi") or "").lower().removeprefix("https://doi.org/")
                out[d] = {"title": plain(w.get("title")), "abstract": inverted(w.get("abstract_inverted_index")),
                          "type": {"article": "journal-article"}.get(w.get("type"), w.get("type")), "year": w.get("publication_year"),
                          "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
                          "first_author": ((w.get("authorships") or [{}])[0].get("author") or {}).get("display_name")}
            if i % 2500 == 0:
                print(f"  {i}/{len(dois)}", flush=True)
    for d in dois:
        if d in out:
            continue
        msg = crossref_work(f, d)
        if msg:
            parts = (msg.get("published") or msg.get("issued") or {}).get("date-parts", [[None]])[0]
            a = (msg.get("author") or [{}])[0]
            out[d] = {"title": plain((msg.get("title") or [""])[0]), "abstract": plain(msg.get("abstract")), "type": msg.get("type"),
                      "year": parts[0] if parts else None, "venue": (msg.get("container-title") or [None])[0],
                      "first_author": " ".join(x for x in [a.get("given"), a.get("family")] if x)}
    return out


def plain(s: str | None) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(s or "")).split())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/Literature/literature.jsonl")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=ROOT / "runtime_data/Literature/discovery_cache")
    args = parser.parse_args()
    f = Fetch(args.cache)
    works = [json.loads(l) for l in args.catalog.read_text(encoding="utf-8").splitlines() if l.strip()]
    have = {(w.get("resolved_doi") or "").lower() for w in works} | {d.lower() for w in works for d in w.get("dois_as_cited") or []}
    have.discard("")
    found: dict[str, list[str]] = defaultdict(list)

    def add(label: str, dois: list[str]):
        for d in dois:
            if label not in found[d]:
                found[d].append(label)
        print(f"{label:60} {len(dois):5}", flush=True)

    for term in CODES + SITES:
        add(f"fulltext:{term}", europepmc(f, f'"{term}"'))
    for name in ["Regional Cabled Array", "Ocean Observatories Initiative", "OOI"]:
        for place in PLACES:
            add(f"fulltext:{name}+{place}", europepmc(f, f'"{name}" AND "{place}"'))
    for name in NAMES:
        for place in PLACES:
            add(f"crossref:{name}+{place}", crossref_search(f, f"{name} {place}"))
        for topic in TOPICS:
            add(f"crossref:{name}+{topic}", crossref_search(f, f"{name} {topic}", rows=200))
    for place in PLACES:
        for topic in TOPICS:
            add(f"crossref:{place}+{topic}", crossref_search(f, f"{place} {topic}", rows=100))
    # Works citing the RCA's foundational papers and the catalog's RCA papers.
    seeds = set(FOUNDATIONAL)
    for w in works:
        text = f"{w.get('resolved_title') or ''} {w.get('abstract') or ''}"
        if w.get("resolved_doi") and (RCA.search(text) or PLACE.search(text)):
            seeds.add(w["resolved_doi"].lower())
    cites = defaultdict(list)
    for doi in sorted(seeds):
        for d in citing(f, doi):
            cites[d].append(doi)
    for d, cited in cites.items():
        found[d].append(f"cites:{len(cited)}")
    print(f"{'cites RCA papers (' + str(len(seeds)) + ' seeds)':60} {len(cites):5}", flush=True)

    rows = []
    todo = [d for d in found if d not in have]
    print(f"looking up {len(todo)} candidates", flush=True)
    meta = lookup(f, todo)
    for doi in todo:
        m = meta.get(doi)
        if not m or m["type"] in SKIP_TYPES:
            continue
        text = f"{m['title']} {m['abstract']}"
        labels = found[doi]
        fulltext_named = any(l.startswith("fulltext:") for l in labels)
        rca, place = bool(RCA.search(text)), bool(PLACE.search(text))
        grade = "strong" if fulltext_named or (rca and place) else "place" if place or rca else "citation" if any(l.startswith("cites:") for l in labels) else "search"
        n_cites = max([int(l.split(":")[1]) for l in labels if l.startswith("cites:")] or [0])
        rows.append({**m, "doi": doi, "grade": grade, "cites_rca_papers": n_cites, "found_by": labels,
                     "title_or_abstract_names": sorted({x.group(0) for x in RCA.finditer(text)} | {x.group(0) for x in PLACE.finditer(text)}),
                     "abstract": m["abstract"][:1500]})
    order = {"strong": 0, "place": 1, "citation": 2, "search": 3}
    rows.sort(key=lambda r: (order[r["grade"]], -r["cites_rca_papers"], -len(r["found_by"]), -(r["year"] or 0)))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    counts = defaultdict(int)
    for r in rows:
        counts[r["grade"]] += 1
    print(json.dumps({"candidates": len(found), "not_in_catalog": len(rows), **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
