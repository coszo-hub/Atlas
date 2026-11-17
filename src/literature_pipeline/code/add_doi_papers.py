#!/usr/bin/env python3
"""Add papers to the canonical catalog by DOI, from Crossref's public metadata.

For papers found outside the OOI Zotero group (Krauss et al. 2023 in Seismica, papers found by searching for RCA
sensors). Each Crossref response is saved under source_material/original_documents/Literature/crossref/ and its
checksum kept as provenance; a DOI already in the catalog is skipped. New records are numbered RCA-LIT-###.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[3]
TYPES = {"journal-article": "journal_article", "posted-content": "preprint", "proceedings-article": "conference_paper",
         "book-chapter": "book_chapter", "dissertation": "thesis", "report": "report"}


def plain(jats: str | None) -> str | None:
    text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(jats or "")).split())
    return re.sub(r"^Abstract\s*:?\s*", "", text, flags=re.I) or None


def record(msg: dict, cid: str, doi: str, saved: Path, sha: str, why: str) -> dict:
    authors = [" ".join(x for x in [a.get("given", "").strip(), a.get("family", "").strip()] if x) or a.get("name", "")
               for a in msg.get("author", [])]
    title = " ".join(html.unescape((msg.get("title") or [""])[0]).split())
    parts = (msg.get("published") or msg.get("issued") or {}).get("date-parts", [[None]])[0]
    year = str(parts[0]) if parts and parts[0] else None
    venue = (msg.get("container-title") or msg.get("institution", [{}]) and [msg.get("institution", [{}])[0].get("name")] or [""])[0] or ""
    vol = f" {msg['volume']}" if msg.get("volume") else ""
    issue = f"({msg['issue']})" if msg.get("issue") else ""
    pages = f": {msg.get('page') or msg.get('article-number')}" if msg.get("page") or msg.get("article-number") else ""
    citation = f"{', '.join(authors)}. ({year}). {title}. {venue}.{vol}{issue}{pages}. https://doi.org/{doi}".replace(" .", ".")
    abstract = plain(msg.get("abstract"))
    api = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    occurrence = {"occurrence_id": f"CROSSREF-{cid}", "canonical_id": cid, "citation": citation, "doi": doi,
                  "collection_name": "RCA literature additions", "source_url": api, "match_method": "verified_crossref_doi"}
    lic = [l.get("URL") for l in msg.get("license", []) if l.get("URL")]
    return {
        "id": cid, "canonical_id": cid, "duplicate_of": None, "citation": citation, "citation_as_extracted": citation,
        "year_as_cited": year, "resource_type": TYPES.get(msg.get("type"), msg.get("type") or "unclassified"),
        "resource_type_status": "verified_crossref_type", "dois_as_cited": [doi],
        "source_links": [{"url": f"https://doi.org/{doi}", "provenance": "Crossref DOI", "verification_status": "retrieved"}],
        "resolved_title": title, "resolved_doi": doi, "resolved_authors": authors, "paper_url": f"https://doi.org/{doi}",
        "abstract": abstract, "abstract_status": "retrieved" if abstract else "not_found",
        "full_text_url": None, "full_text_status": "not_checked", "license": lic[0] if lic else None,
        "abstract_source_url": api if abstract else None, "metadata_source_url": api,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_rights": None,
        "provenance": {"source_document": str(saved.relative_to(ROOT)), "source_sha256": sha, "method": "verified_crossref_doi"},
        "notes": why, "source_occurrence_ids": [occurrence["occurrence_id"]], "source_occurrences": [occurrence],
        "source_occurrence_count": 1, "schema_version": "1.3-runtime",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dois", nargs="+")
    parser.add_argument("--why", default="Added by DOI for RCA Atlas.", help="Why the paper was added (kept in its notes).")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/Literature/literature.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    works = [json.loads(line) for line in args.catalog.read_text(encoding="utf-8").splitlines() if line.strip()]
    have = {(w.get("resolved_doi") or "").lower() for w in works} | {d.lower() for w in works for d in w.get("dois_as_cited") or []}
    n = max([int(m.group(1)) for w in works if (m := re.fullmatch(r"RCA-LIT-(\d+)", w["id"]))] or [0])
    folder = ROOT / "source_material/original_documents/Literature/crossref"
    folder.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=60, headers={"User-Agent": "RCA-Atlas/1.0"})
    added = []
    for doi in (d.strip().lower().removeprefix("https://doi.org/") for d in args.dois):
        if doi in have:
            print(json.dumps({"doi": doi, "status": "already_present"}))
            continue
        resp = client.get(f"https://api.crossref.org/works/{quote(doi, safe='')}")
        if resp.status_code != 200:
            print(json.dumps({"doi": doi, "status": f"crossref_{resp.status_code}"}))
            continue
        saved = folder / (re.sub(r"[^a-z0-9]+", "_", doi) + ".json")
        saved.write_bytes(resp.content)
        n += 1
        rec = record(resp.json()["message"], f"RCA-LIT-{n:03d}", doi, saved, hashlib.sha256(resp.content).hexdigest(), args.why)
        added.append(rec); have.add(doi)
        print(json.dumps({"doi": doi, "status": "added", "id": rec["id"], "title": rec["resolved_title"][:90], "abstract": bool(rec["abstract"])}))
    if added and not args.dry_run:
        args.catalog.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in works + added), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
