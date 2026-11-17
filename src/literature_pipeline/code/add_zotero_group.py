#!/usr/bin/env python3
"""Add the OOI Zotero group's RCA and Oregon-margin papers that the catalog missed.

The catalog was assembled from two of the group's collections (Regional Cabled Array, Coastal Endurance Array), but many
RCA papers are filed only under "All Publications" (Kidiwela et al. 2026, Lee et al. 2024, Wang et al. 2024 ...). This
reads a saved snapshot of the whole group's top-level items and appends, as new OOI-ZOT records, the ones not already
in the catalog (by DOI, else title) that are in either collection or whose title or abstract names an RCA or
Endurance place and no other OOI array. Existing records are left as they are.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent / "zotero_expansion"))
from assemble_zotero import citation, clean_abstract, clean_literal, norm_doi, norm_title, resource_type, split_urls  # noqa: E402

GROUP = "https://www.zotero.org/groups/5351356/ooipublications"
NAMES = {"RMTSE2IH": "Regional Cabled Array", "E5UH7L89": "Coastal Endurance Array", "65LNC4QU": "All Publications",
         "QWYQ3873": "All Arrays", "NH4EBT4E": "Yes", "YUU2WN82": "Cyberinfrastructure"}
OURS = {"RMTSE2IH", "E5UH7L89"}
SITE = re.compile(r"axial|hydrate ridge|regional cabled|cabled array|slope base|endurance|oregon|washington (shelf|coast)"
                  r"|juan de fuca|cascadia|newport|ashes|international district|\bRCA\b|OOI (seafloor )?cables?", re.I)
OTHER = re.compile(r"station papa|irminger|pioneer|argentine|southern ocean array|new england", re.I)
OURS_TOO = re.compile(r"axial|hydrate|regional cabled|endurance|oregon|cascadia", re.I)


def wanted(d: dict) -> bool:
    text = f"{d.get('title') or ''} {d.get('abstractNote') or ''}"
    if OURS & set(d.get("collections", [])):
        return True
    return bool(SITE.search(text)) and not (OTHER.search(text) and not OURS_TOO.search(text))


def record(item: dict, cid: str, snapshot: str, sha: str) -> dict:
    d = item["data"]
    doi = norm_doi(d.get("DOI"))
    abstract = clean_abstract(d.get("abstractNote")) or None
    year = (item.get("meta", {}).get("parsedDate") or d.get("date") or "")[:4]
    urls = split_urls(d.get("url"))
    api, page = item["links"]["self"]["href"], item["links"]["alternate"]["href"]
    collections = [{"key": k, "name": NAMES.get(k, k), "url": f"{GROUP}/collections/{k}/collection"} for k in d.get("collections", [])]
    occurrence = {"occurrence_id": f"ZOTERO-GROUP-{item['key']}", "canonical_id": cid, "zotero_key": item["key"],
                  "collection_key": (d.get("collections") or [None])[0], "collection_name": "OOIPublications Zotero group",
                  "title": d.get("title"), "doi": doi or None, "item_type": d.get("itemType"), "date": d.get("date"),
                  "zotero_item_url": page, "zotero_api_url": api}
    dc = dict(d, title=clean_literal(d.get("title")))
    authors = [c.get("name") or " ".join(x for x in [c.get("firstName", "").strip(), c.get("lastName", "").strip()] if x)
               for c in d.get("creators", []) if c.get("creatorType") == "author"]
    return {
        "id": cid, "canonical_id": cid, "duplicate_of": None, "citation_as_extracted": citation(d), "citation": citation(dc),
        "year_as_cited": year if re.fullmatch(r"\d{4}", year) else None, "resource_type": resource_type(d.get("itemType")),
        "resource_type_status": "classified_from_zotero_item_type", "dois_as_cited": [doi] if doi else [],
        "source_links": [{"url": page, "provenance": "OOI Zotero item", "verification_status": "retrieved"},
                         *[{"url": u, "provenance": "Zotero URL field", "verification_status": "not_checked"} for u in urls]],
        "verified_metadata": [], "abstract": abstract, "abstract_status": "retrieved" if abstract else "not_found",
        "full_text_url": None, "full_text_status": "not_checked", "review_notes": [],
        "provenance": {"source_document": snapshot, "source_sha256": sha, "source_url": GROUP, "collections": collections,
                       "zotero_key": item["key"], "method": "ooi_zotero_group_expansion"},
        "source_occurrence_ids": [occurrence["occurrence_id"]], "source_occurrences": [occurrence], "source_occurrence_count": 1,
        "resolved_title": dc["title"], "resolved_doi": doi or None, "resolved_authors": authors,
        "paper_url": f"https://doi.org/{doi}" if doi else (urls[0] if urls else page),
        "abstract_source_url": api if abstract else None, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "metadata_source_url": api, "license": None, "source_rights": d.get("rights") or None,
        "landing_page_url": urls[0] if urls else None, "zotero_item_url": page, "zotero_item_key": item["key"],
        "source_collections": collections,
        "notes": ("Abstract and bibliographic metadata were supplied by the public OOI Zotero group; the abstract is source "
                  "text, not an agent-generated summary." if abstract else "No abstract was present in the public Zotero item metadata."),
        "attempts": [], "schema_version": "1.3-runtime",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/Literature/literature.jsonl")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "source_material/original_documents/Literature/ooi_zotero_group_2026-11-16.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    works = [json.loads(line) for line in args.catalog.read_text(encoding="utf-8").splitlines() if line.strip()]
    raw = args.snapshot.read_bytes()
    items = json.loads(raw)
    dois = {norm_doi(w.get("resolved_doi")) for w in works} | {norm_doi(x) for w in works for x in w.get("dois_as_cited") or []}
    titles = {norm_title(w.get("resolved_title")) for w in works} - {""}
    keys = {w.get("zotero_item_key") for w in works}
    n = max(int(m.group(1)) for w in works if (m := re.fullmatch(r"OOI-ZOT-(\d+)", w["id"])))
    added = []
    for item in items:
        d = item["data"]
        doi, title = norm_doi(d.get("DOI")), norm_title(d.get("title"))
        if item["key"] in keys or (doi and doi in dois) or title in titles or not wanted(d):
            continue
        n += 1
        added.append(record(item, f"OOI-ZOT-{n:03d}", args.snapshot.name, hashlib.sha256(raw).hexdigest()))
        dois.add(doi); titles.add(title)
    for r in added:
        print(r["id"], r["year_as_cited"], r["resolved_title"][:90])
    if not args.dry_run and added:
        args.catalog.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in works + added), encoding="utf-8")
    print(json.dumps({"added": len(added), "works": len(works) + (0 if args.dry_run else len(added))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
