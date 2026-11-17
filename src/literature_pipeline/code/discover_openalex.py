#!/usr/bin/env python3
"""Find papers about the RCA's instruments and sites in OpenAlex that the catalog does not have.

Searches OpenAlex (full text where it has it, else title and abstract) for every OO station code and RCA/Endurance
site designator on the map, for the RCA's names with each site and instrument type, and for the papers citing the
RCA's foundational papers; records which searches found each work; and writes the works not in the catalog (by DOI,
else title) to a report for review. Nothing is added to the catalog here: add_doi_papers.py does that, after review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
API = "https://api.openalex.org/works"
CODES = ["AXAS1", "AXAS2", "AXBA1", "AXCC1", "AXCC2", "AXEC1", "AXEC2", "AXEC3", "AXID1", "HYS11", "HYS12", "HYS13",
         "HYS14", "HYSB1", "CZMID", "CZOFF", "CZOSH", "CZSHF"]
SITES = ["CE02SHBP", "CE04OSBP", "CE04OSPD", "CE04OSPS", "RS01SBPD", "RS01SBPS", "RS01SLBS", "RS01SUM1", "RS01SUM2",
         "RS03ASHS", "RS03AXBS", "RS03AXPD", "RS03AXPS", "RS03CCAL", "RS03ECAL", "RS03INT1", "RS03INT2"]
NAMES = ['"Regional Cabled Array"', '"Cabled Axial Seamount"', '"OOI cabled array"', '"Ocean Observatories Initiative" cabled']
PLACES = ['"Axial Seamount"', '"Hydrate Ridge"', '"Slope Base"', '"Oregon Offshore"', '"Endurance Array"', '"Oregon Shelf"']
KINDS = ["seismometer", "hydrophone", "pressure", "tilt", "BOTPT", "COVIS", "profiler", "CTD", "camera", "CAMHD",
         "mass spectrometer", "ADCP", "temperature", "methane", "osmotic", "fluid sampler", "geodesy", "fiber", '"distributed acoustic sensing"']
TOPICS = ["seismometer", "hydrophone", "seafloor pressure", "tilt", "BOTPT", "COVIS", "shallow profiler", "deep profiler",
          "CTD", "camera", "mass spectrometer", "methane", "hydrothermal", "eruption", "earthquakes", "geodesy",
          '"distributed acoustic sensing"', "whale", '"ambient noise"', "oxygen", "nitrate", "currents", "temperature"]
# The RCA's site names alone, in full text and in titles and abstracts: papers on Hydrate Ridge, Slope Base or Axial
# that never say OOI (ship surveys, earlier observatories, models) are about the features the sensors watch.
SITE_NAMES = ['"Axial Seamount"', '"Axial Volcano"', '"Hydrate Ridge"', '"Southern Hydrate Ridge"', '"Slope Base" AND Oregon',
              '"Endurance Array"', '"Oregon Offshore" AND cabled', '"ASHES" AND Axial', '"International District" AND Axial',
              '"Axial caldera"', '"Coaxial" AND "Juan de Fuca"',
              '"Hydrate Ridge" AND Cascadia', '"Axial Seamount" AND "Juan de Fuca"', '"Slope Base" AND Cascadia']
# Named features at the RCA sites: vents and chimneys, seeps, lava flows and structures, with the place that
# disambiguates them ("Inferno" alone is everywhere).
FEATURES = ['"Inferno" AND "Axial" AND "Axial Seamount"', '"Mushroom" AND "ASHES" AND "Axial Seamount"', '"El Gordo" AND "Axial" AND "Axial Seamount"', '"Escargot" AND "Axial" AND "Axial Seamount"', '"Diva" AND "Axial" AND "Axial Seamount"',
            '"Castle" AND "International District" AND Axial', '"Tiny Towers" AND Axial', '"Anemone" AND "ASHES" AND "Axial Seamount"', '"Hell" AND "ASHES" AND "Axial Seamount"', '"Virgin" AND "ASHES" AND "Axial Seamount"',
            '"CASM" AND "Axial" AND "Axial Seamount"', '"north rift" AND "Axial Seamount"', '"south rift" AND "Axial Seamount"', '"2015 eruption" AND "Axial"',
            '"2011 eruption" AND "Axial"', '"1998 eruption" AND "Axial"', '"magma reservoir" AND "Axial"', '"ring fault" AND "Axial"',
            '"Pinnacle" AND "Hydrate Ridge"', '"Einstein\'s Grotto"', '"Southern Hydrate Ridge" AND seep',
            '"deformation front" AND Cascadia AND Oregon', '"Coaxial segment"', '"Vixen" AND "Axial" AND "Axial Seamount"']
# The RCA's design and first-results papers: works citing them are likely to use its data.
FOUNDATIONAL = ["10.1016/j.margeo.2014.03.010", "10.3389/fmars.2019.00074", "10.1126/science.aah5563",
                "10.1126/science.aah4666", "10.1126/science.aah4529", "10.5670/oceanog.2018.111"]
RELEVANT = re.compile(r"Axial|Hydrate Ridge|Slope Base|Regional Cabled|cabled (array|observator)|Ocean Observatories Initiative|"
                      r"\bOOI\b|\bRCA\b|Endurance|Oregon (shelf|slope|margin|offshore)|Cascadia|Juan de Fuca|" + "|".join(CODES), re.I)
SELECT = "id,doi,title,publication_year,type,primary_location,open_access,cited_by_count,abstract_inverted_index,authorships"


def abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    words = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in words)


def api_key() -> str | None:
    """OPENALEX_API_KEY from the environment or .env: without one, OpenAlex gives an IP a shared $0.10 a day."""
    if os.environ.get("OPENALEX_API_KEY"):
        return os.environ["OPENALEX_API_KEY"]
    env = ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("OPENALEX_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


SPENT = {"remaining_usd": None}
STOP_BELOW_USD = 0.03


def search(client: httpx.Client, flt: str, cap: int, cache: Path) -> list[dict]:
    """One search's works, kept in the cache so a rerun after a rate limit resumes where it stopped."""
    saved = cache / (hashlib.sha256(f"{flt}|{cap}".encode()).hexdigest()[:20] + ".json")
    if saved.exists():
        return json.loads(saved.read_text())
    # A search cached under a smaller cap that it did not reach is complete: reuse it.
    for smaller in (2000,):
        old = cache / (hashlib.sha256(f"{flt}|{smaller}".encode()).hexdigest()[:20] + ".json")
        if smaller < cap and old.exists() and len(rows := json.loads(old.read_text())) < smaller:
            return rows
    out, cursor = [], "*"
    key = api_key()
    while cursor and len(out) < cap:
        params = {"filter": flt, "per-page": 200, "cursor": cursor, "select": SELECT, **({"api_key": key} if key else {})}
        for attempt in range(4):
            r = client.get(API, params=params)
            if r.status_code == 200:
                break
            if r.status_code == 429 and "Remaining-USD" in str(r.headers) and r.headers.get("X-RateLimit-Remaining-USD") in ("0", "0.0"):
                break
            time.sleep(2 ** attempt)
        left = r.headers.get("X-RateLimit-Remaining-USD")
        prepaid = r.headers.get("X-RateLimit-Prepaid-Remaining-USD")
        if left is not None:
            SPENT["remaining_usd"] = float(left) + float(prepaid or 0)
            if SPENT["remaining_usd"] < STOP_BELOW_USD:
                raise SystemExit(f"Stopping: OpenAlex budget down to ${SPENT['remaining_usd']:.3f}; rerun later to resume.")
        if r.status_code == 429:
            raise SystemExit(f"OpenAlex's daily budget is used up (at {flt}); set OPENALEX_API_KEY, or rerun tomorrow to resume.")
        r.raise_for_status()
        body = r.json()
        out += body["results"]
        cursor = body["meta"].get("next_cursor") if body["results"] else None
        time.sleep(0.2)
    saved.write_text(json.dumps(out))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/Literature/literature.jsonl")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cap", type=int, default=2000, help="Most works kept from one search.")
    parser.add_argument("--cache", type=Path, default=ROOT / "runtime_data/Literature/openalex_discovery")
    args = parser.parse_args()
    client = httpx.Client(timeout=90, headers={"User-Agent": "RCA-Atlas/1.0"})
    norm = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())
    works = [json.loads(l) for l in args.catalog.read_text(encoding="utf-8").splitlines() if l.strip()]
    have_doi = {(w.get("resolved_doi") or "").lower() for w in works} | {d.lower() for w in works for d in w.get("dois_as_cited") or []}
    have_title = {norm(w.get("resolved_title")) for w in works} - {""}

    queries = []
    queries += [(f"code:{c}", f"fulltext.search:{c}") for c in CODES]
    queries += [(f"site:{s}", f"fulltext.search:{s}") for s in SITES]
    for n in NAMES:
        queries += [(f"name:{n}", f"fulltext.search:{n}"), (f"name-abstract:{n}", f"title_and_abstract.search:{n}")]
    for p in PLACES:
        queries.append((f"ooi+place:{p}", f'fulltext.search:"Ocean Observatories Initiative" {p}'))
        queries.append((f"ooi+place-abstract:{p}", f'title_and_abstract.search:(OOI OR "Ocean Observatories Initiative" OR "cabled array") {p}'))
    for k in KINDS:
        queries.append((f"rca+kind:{k}", f'fulltext.search:"Regional Cabled Array" {k}'))
    for p in PLACES:
        for t in TOPICS:
            queries.append((f"place+topic:{p}+{t}", f"fulltext.search:{p} {t}"))
    queries += [(f"feature:{x}", f"fulltext.search:{x}") for x in FEATURES]
    for x in SITE_NAMES:
        queries += [(f"sitename:{x}", f"fulltext.search:{x}"), (f"sitename-abstract:{x}", f"title_and_abstract.search:{x}")]
    args.cache.mkdir(parents=True, exist_ok=True)
    for doi in FOUNDATIONAL:
        w = client.get(f"{API}/doi:{doi}", params={"select": "id,title", **({"api_key": api_key()} if api_key() else {})})
        if w.status_code == 200:
            queries.append((f"cites:{doi}", f"cites:{w.json()['id'].rsplit('/', 1)[-1]}"))

    # Works citing any RCA paper the catalog has (title or abstract naming the RCA or an RCA place), 50 per query.
    seeds = sorted({(w.get("resolved_doi") or "").lower() for w in works if w.get("resolved_doi")
                    and RELEVANT.search(f"{w.get('resolved_title') or ''} {w.get('abstract') or ''}")} | set(FOUNDATIONAL))
    ids = []
    for i in range(0, len(seeds), 50):
        batch = seeds[i:i + 50]
        r = client.get(API, params={"filter": "doi:" + "|".join(batch), "per-page": 50, "select": "id",
                                    **({"api_key": api_key()} if api_key() else {})})
        if r.status_code == 200:
            ids += [w["id"].rsplit("/", 1)[-1] for w in r.json()["results"]]
    for i in range(0, len(ids), 50):
        queries.append((f"cites-catalog:{i // 50}", "cites:" + "|".join(ids[i:i + 50])))
    print(f"{len(seeds)} RCA papers in the catalog to follow citations from ({len(ids)} found in OpenAlex)", flush=True)

    found: dict[str, dict] = {}
    hits: dict[str, list[str]] = defaultdict(list)
    for label, flt in queries:
        got = search(client, flt, args.cap, args.cache)
        for w in got:
            found[w["id"]] = w
            hits[w["id"]].append(label)
        print(f"{label:60} {len(got):5}  budget left ${SPENT['remaining_usd'] if SPENT['remaining_usd'] is not None else float('nan'):.3f}", flush=True)

    rows = []
    for wid, w in found.items():
        doi = (w.get("doi") or "").lower().removeprefix("https://doi.org/")
        if (doi and doi in have_doi) or norm(w.get("title")) in have_title:
            continue
        text = f"{w.get('title') or ''} {abstract(w.get('abstract_inverted_index'))}"
        labels = hits[wid]
        strong = [l for l in labels if l.startswith(("code:", "site:", "name:", "rca+kind:", "ooi+place:"))]
        rows.append({
            "openalex_id": wid, "doi": doi or None, "title": w.get("title"), "year": w.get("publication_year"),
            "type": w.get("type"), "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
            "first_author": ((w.get("authorships") or [{}])[0].get("author") or {}).get("display_name"),
            "open_access": (w.get("open_access") or {}).get("is_oa"), "cited_by": w.get("cited_by_count"),
            "found_by": labels if len(labels) <= 12 else labels[:12] + [f"+{len(labels) - 12} more"],
            "names_rca_in_full_text": bool(strong),
            "abstract_names_rca_place": bool(RELEVANT.search(text)), "abstract": abstract(w.get("abstract_inverted_index"))[:1500],
        })
    rows.sort(key=lambda r: (not r["names_rca_in_full_text"], not r["abstract_names_rca_place"], -len(r["found_by"]), -(r["year"] or 0)))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(json.dumps({"searches": len(queries), "works_found": len(found), "not_in_catalog": len(rows),
                      "named_in_full_text": sum(r["names_rca_in_full_text"] for r in rows),
                      "abstract_only": sum(not r["names_rca_in_full_text"] and r["abstract_names_rca_place"] for r in rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
