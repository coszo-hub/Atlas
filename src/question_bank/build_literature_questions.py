#!/usr/bin/env python3
"""Literature questions (type 1) and paper summaries (type 10), from the authored files in authored/.

Each authored entry is one paper, read and written by hand from its abstract: the key points a summary must give
(as [label, regex]) and one or two questions answerable from that paper, each with the facts an answer must state.
This builds the questions: summaries are asked by author and year ("tell me about Chadwick et al. (2012)"), with a
few words of the title when the same first author has another paper that year; every answer must cite the paper.

Checks: every fact's pattern must match the paper's own abstract or full text (a fact the paper does not state is an
authoring error and fails the build). Split by paper: papers already asked about (the literature and content evals)
are train; the rest alternate by hash within their area.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SEED = "rca-atlas-question-bank-2026-11-17"


def h(*parts: str) -> int:
    return int(hashlib.sha256("|".join((SEED, *parts)).encode()).hexdigest()[:12], 16)


def surname(work: dict, doc: dict) -> str:
    """The first author's surname, from "Seiple, Jason Eric", "Li, S., ...", "Marcon Y, ...", "F. Waldhauser, ..." or
    "William W. Chadwick, ..."."""
    authors = work.get("resolved_authors") or []
    text = (authors[0] if authors else work.get("citation") or doc.get("citation") or "").strip()
    m = re.match(r"([A-Z][\w'’\-]+), (?:[A-Z]\.|[A-Z][a-z]+)", text)   # Surname, Given
    if m:
        return m.group(1)
    head = re.split(r"[,(]", text, 1)[0]
    words = [w for w in head.replace(".", ". ").split() if not re.fullmatch(r"[A-Z]{1,3}\.?|Jr\.?", w)]
    return words[-1].rstrip(".") if words else "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", type=Path, default=HERE / "literature_train.jsonl")
    parser.add_argument("--blind", type=Path, default=HERE / "blind" / "literature_blind.jsonl")
    args = parser.parse_args()
    works = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/Literature/literature.jsonl").read_text().splitlines() if l.strip()}
    docs = {json.loads(l)["document_id"]: json.loads(l) for l in (ROOT / "data/Literature/documents.jsonl").read_text().splitlines() if l.strip()}
    fulltext = defaultdict(list)
    for line in (ROOT / "data/LiteratureFullText/chunks.jsonl").read_text().splitlines():
        c = json.loads(line)
        fulltext[c["document_id"]].append(c.get("text") or "")
    entries = [e for path in sorted((HERE / "authored").glob("literature_batch*.json")) for e in json.loads(path.read_text())]

    # Papers already asked about: the content eval's papers and the literature eval's answers.
    bank = [json.loads(l) for l in (HERE / "question_bank.jsonl").read_text().splitlines() if l.strip()]
    seen = {r["gold"]["paper"] for r in bank if r["gold_kind"] == "paper_facts"}
    for r in bank:
        if r["gold_kind"] == "paper_title_regex":
            rx = re.compile(r["gold"], re.I)
            seen |= {k for k, d in docs.items() if rx.search(d.get("title") or "")}

    by_author_year = defaultdict(list)
    for k, d in docs.items():
        by_author_year[(surname(works.get(k, {}), d).lower(), d.get("publication_year"))].append(k)

    rows, errors = [], []
    for e in entries:
        pid = e["paper"]
        doc, work = docs[pid], works.get(pid, {})
        text = unicodedata.normalize("NFC", " ".join([doc.get("title") or "", doc.get("abstract") or "", *fulltext.get(pid, [])]))
        for label, rx in e["summary"] + [f for q in e["questions"] for f in q["facts"]]:
            if not re.search(rx, text, re.I):
                errors.append(f"{pid}: '{label}' ({rx}) is not in the paper")
        name, year = surname(work, doc), doc.get("publication_year")
        cite = {"paper": pid, "doi": doc.get("doi"), "title": doc.get("title")}
        ambiguous = len(by_author_year[(name.lower(), year)]) > 1
        hint = " on " + " ".join((doc.get("title") or "").split()[:6]) if ambiguous else ""
        etal = " et al." if len(work.get("resolved_authors") or []) != 1 else ""
        for text_q in sorted([f"Can you tell me about the paper by {name}{etal} ({year}){hint}?",
                              f"what is {name} {year}{hint} about", f"Summarize {name}{etal} ({year}){hint}."],
                             key=lambda t: h(pid, t))[:2]:
            rows.append({"type": 10, "type_name": "paper_summary", "entity": pid, "question": text_q,
                         "gold": {**cite, "facts": e["summary"], "min_facts": 2}, "gold_kind": "paper_summary"})
        for q in e["questions"]:
            rows.append({"type": 1, "type_name": "literature", "entity": pid, "question": q["q"],
                         "gold": {**cite, "facts": q["facts"]}, "gold_kind": "paper_facts"})
    if errors:
        print("\n".join(errors))
        raise SystemExit(f"{len(errors)} facts are not in their papers")

    # Split by paper, alternating within each area (the selection's topic of the paper's first fact).
    papers = sorted({r["entity"] for r in rows}, key=lambda p: h(p))
    split, i = {}, 0
    for p in papers:
        if p in seen:
            split[p] = "train"
        else:
            split[p] = "train" if i % 2 == 0 else "blind"
            i += 1
    for r in rows:
        r["split"] = split[r["entity"]]
        r["source"] = "authored_from_paper"
        r["id"] = f"lit:{r['type']}:{h(r['entity'], r['question']) % 10**8:08d}"
    args.blind.parent.mkdir(parents=True, exist_ok=True)
    for path, part in ((args.train, "train"), (args.blind, "blind")):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if r["split"] == part), encoding="utf-8")
    count = defaultdict(lambda: defaultdict(int))
    for r in rows:
        count[f"{r['type']} {r['type_name']}"][r["split"]] += 1
    print(json.dumps({"papers": len(papers), "seen_papers_train": sum(p in seen for p in papers), "questions": len(rows),
                      "by_type": {k: dict(v) for k, v in count.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
