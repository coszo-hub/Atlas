#!/usr/bin/env python3
"""Append the screened discovery results to the canonical catalog, from OpenAlex's metadata.

Reads the screened list (review_candidates.py's rows that were kept), looks each work up in OpenAlex 50 at a time (by
OpenAlex ID, else DOI) for its title, authors, venue, year, abstract, open-access location and licence, saves the
responses as provenance, and appends one RCA-LIT record per work not already in the catalog (by DOI or title).
Existing records are never changed.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_openalex import api_key  # noqa: E402

API = "https://api.openalex.org/works"
SELECT = ("id,doi,title,publication_year,publication_date,type,primary_location,best_oa_location,open_access,"
          "authorships,biblio,abstract_inverted_index")
TYPES = {"article": "journal_article", "journal-article": "journal_article", "preprint": "preprint", "posted-content": "preprint",
         "dissertation": "thesis", "book-chapter": "book_chapter", "book": "book", "conference-paper": "conference_paper",
         "proceedings-article": "conference_paper", "conference-abstract": "conference_abstract", "report": "report",
         "review": "review_article", "other": "other"}
WHY = {"1_uses_rca": "Uses RCA or Endurance instruments or data",
       "5_meeting_abstract": "Meeting abstract on RCA or Endurance instruments or data",
       "2_rca_place": "About an RCA site or feature (Axial Seamount, Hydrate Ridge, ASHES, CoAxial, the Oregon margin)",
       "3_text_place": "Names RCA sites or instruments in its full text"}


def plain(s: str | None) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(s or "")).split())


def abstract(inv: dict | None) -> str:
    return " ".join(w for _, w in sorted((p, w) for w, ps in (inv or {}).items() for p in ps))


def fetch(client: httpx.Client, flt: str, values: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(values), 50):
        r = client.get(API, params={"filter": f"{flt}:" + "|".join(values[i:i + 50]), "per-page": 50, "select": SELECT,
                                    **({"api_key": api_key()} if api_key() else {})})
        r.raise_for_status()
        out += r.json()["results"]
    return out


def record(w: dict, cid: str, row: dict, saved: str, sha: str) -> dict:
    doi = (w.get("doi") or "").lower().removeprefix("https://doi.org/") or None
    title = plain(w.get("title"))
    authors = [((a.get("author") or {}).get("display_name") or "").strip() for a in w.get("authorships") or []]
    authors = [a for a in authors if a]
    src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    b = w.get("biblio") or {}
    year = w.get("publication_year")
    pages = f": {b['first_page']}" + (f"–{b['last_page']}" if b.get("last_page") and b["last_page"] != b["first_page"] else "") if b.get("first_page") else ""
    link = f"https://doi.org/{doi}" if doi else w["id"]
    who = ", ".join(authors[:12]) + (" et al." if len(authors) > 12 else "")
    citation = f"{who}. ({year}). {title}." + (f" {src}." if src else "") + (f" {b['volume']}" if b.get("volume") else "") + \
               (f"({b['issue']})" if b.get("issue") else "") + pages + f" {link}"
    text = abstract(w.get("abstract_inverted_index")) or None
    oa = w.get("best_oa_location") or {}
    occurrence = {"occurrence_id": f"OPENALEX-{w['id'].rsplit('/', 1)[-1]}", "canonical_id": cid, "citation": citation,
                  "doi": doi, "collection_name": "RCA literature discovery (OpenAlex, Crossref, Europe PMC, OpenCitations)",
                  "source_url": w["id"], "match_method": "discovery_search_then_review"}
    return {
        "id": cid, "canonical_id": cid, "duplicate_of": None, "citation": citation, "citation_as_extracted": citation,
        "year_as_cited": str(year) if year else None, "publication_year": year,
        "resource_type": TYPES.get(w.get("type"), w.get("type") or "unclassified"), "resource_type_status": "openalex_type",
        "dois_as_cited": [doi] if doi else [],
        "source_links": [{"url": link, "provenance": "OpenAlex", "verification_status": "retrieved"}],
        "resolved_title": title, "resolved_doi": doi, "resolved_authors": authors, "paper_url": link,
        "abstract": text, "abstract_status": "retrieved" if text else "not_found",
        "full_text_url": oa.get("pdf_url") or oa.get("landing_page_url"), "full_text_status": "not_checked",
        "license": oa.get("license"), "abstract_source_url": w["id"] if text else None, "metadata_source_url": w["id"],
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_rights": None,
        "provenance": {"source_document": saved, "source_sha256": sha, "method": "openalex_metadata",
                       "found_by": row["found_by"][:20], "tier": row["tier"]},
        "notes": f"{WHY.get(row['tier'], 'Found by the RCA literature discovery')}; found by searching OpenAlex, Crossref, "
                 f"Europe PMC and OpenCitations for the RCA's stations, sites and features, and kept on review (2026-11-16). "
                 "The abstract is OpenAlex's, reconstructed from its word index.",
        "source_occurrence_ids": [occurrence["occurrence_id"]], "source_occurrences": [occurrence], "source_occurrence_count": 1,
        "schema_version": "1.3-runtime",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screened", type=Path, help="JSON list of the kept rows")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/Literature/literature.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rows = json.loads(args.screened.read_text())
    works = [json.loads(l) for l in args.catalog.read_text(encoding="utf-8").splitlines() if l.strip()]
    norm = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())[:80]
    have_doi = {(w.get("resolved_doi") or "").lower() for w in works} - {""}
    have_title = {norm(w.get("resolved_title")) for w in works} - {""}
    client = httpx.Client(timeout=90, headers={"User-Agent": "RCA-Atlas/1.0"})
    by_id = [r["openalex_id"].rsplit("/", 1)[-1] for r in rows if r.get("openalex_id")]
    by_doi = [r["doi"] for r in rows if not r.get("openalex_id") and r.get("doi")]
    found = fetch(client, "ids.openalex", by_id) + fetch(client, "doi", by_doi)
    raw = json.dumps(found, ensure_ascii=False).encode()
    saved = ROOT / "source_material/original_documents/Literature/openalex_discovered_2026-11-16.json"
    saved.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    meta = {}
    for w in found:
        meta[w["id"]] = w
        if w.get("doi"):
            meta[w["doi"].lower().removeprefix("https://doi.org/")] = w
    n = max([int(m.group(1)) for w in works if (m := re.fullmatch(r"RCA-LIT-(\d+)", w["id"]))] or [0])
    added, missing = [], []
    for row in rows:
        w = meta.get(row.get("openalex_id")) or meta.get(row.get("doi") or "")
        if not w:
            missing.append(row["title"])
            continue
        doi = (w.get("doi") or "").lower().removeprefix("https://doi.org/")
        if (doi and doi in have_doi) or norm(w.get("title")) in have_title:
            continue
        n += 1
        rec = record(w, f"RCA-LIT-{n:03d}", row, str(saved.relative_to(ROOT)), sha)
        added.append(rec)
        have_title.add(norm(rec["resolved_title"]))
        if doi:
            have_doi.add(doi)
    if added and not args.dry_run:
        args.catalog.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in works + added), encoding="utf-8")
    print(json.dumps({"screened": len(rows), "found_in_openalex": len(found), "added": len(added),
                      "with_abstract": sum(bool(r["abstract"]) for r in added), "open_access_link": sum(bool(r["full_text_url"]) for r in added),
                      "not_found": missing[:10], "works": len(works) + (0 if args.dry_run else len(added))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
