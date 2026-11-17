#!/usr/bin/env python3
"""Literature-link questions (types 2, 3, 4, 5, 8 and 9), from the gold read by hand in authored/.

- authored/sensor_papers.json: for 38 sensors, the papers that used the sensor's data and those that only mention it,
  judged from the candidates gather_sensor_candidates.py finds across the whole corpus.
- authored/paper_topics.json: for 136 papers (those that used a sensor above, and the 75 literature-question papers),
  the methods each applies and the concepts it studies (src/literature_links/vocabulary.json), whether it analyzes RCA
  data, and its study sites.

Questions: 2 which papers used / mention a sensor; 3 a paper's methods; 4 a paper's concepts, and the papers that study
a concept; 5 the papers about a site; 8 the methods applied to a sensor's data (from the papers that used it); 9 the
papers that did a method with RCA data. Paper sets for 3/4/5/9 are over the 136 judged papers only (gold "scope"): a
paper outside them is unknown, not wrong.

Split by entity, consistent with the other files: a sensor takes the split generate_source_questions.py gives it, a
paper the split build_literature_questions.py gives it; new entities (methods, concepts, other papers and sensors, and
a site's papers, which no other question asks) are train when a question already asked names them, otherwise
alternated by hash within their group.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import build_literature_questions as lit
import generate_source_questions as gen

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
h = gen.h
TYPE_NAMES = {2: "paper_sensor", 3: "paper_method", 4: "paper_concept", 5: "site_papers", 8: "method_sensor", 9: "method_papers"}
SITE_ENTITY = {   # paper site code -> the type 6 site entity it shares a split with, and how a question names it
    "axial": ("Axial Seamount", ["Axial Seamount", "axial"]),
    "ashes": ("the ASHES vent field", ["the ASHES vent field", "ashes"]),
    "ccal": ("the Axial Central Caldera", ["the Axial Central Caldera", "central caldera"]),
    "axbase": ("Axial Base", ["Axial Base", "axial base"]),
    "shr": ("Southern Hydrate Ridge", ["Southern Hydrate Ridge", "southern hydrate ridge"]),
    "hr": ("Southern Hydrate Ridge", ["Hydrate Ridge", "hydrate ridge"]),
    "slope": ("Oregon Slope Base", ["Oregon Slope Base", "slope base"]),
    "shelf": ("Oregon Shelf", ["the Oregon Shelf", "the oregon shelf"]),
    "offshore": ("Oregon Offshore", ["Oregon Offshore", "oregon offshore"]),
}
SITE_TAKES = {"axial": {"axial", "ashes", "ccal", "ecal", "axbase"}, "hr": {"shr", "nhr", "hr"}}   # broad site -> codes


def load(path: Path) -> dict:
    return {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", type=Path, default=HERE / "links_train.jsonl")
    parser.add_argument("--blind", type=Path, default=HERE / "blind" / "links_blind.jsonl")
    args = parser.parse_args()
    sensors = load(HERE / "authored/sensor_papers.json")
    topics = load(HERE / "authored/paper_topics.json")
    voc = {e["id"]: e for e in json.loads((ROOT / "src/literature_links/vocabulary.json").read_text())}
    docs = {json.loads(l)["document_id"]: json.loads(l) for l in (ROOT / "data/Literature/documents.jsonl").read_text().splitlines() if l.strip()}
    works = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/Literature/literature.jsonl").read_text().splitlines() if l.strip()}
    src = gen.Sources()

    bad = [f"{s}: {p}" for s, v in sensors.items() for p in v["used"] + v["mentioned"] if p not in docs]
    bad += [f"{s}: in both" for s, v in sensors.items() if set(v["used"]) & set(v["mentioned"])]
    bad += [f"{p}: not a paper" for p in topics if p not in docs]
    bad += [f"{p}: {x}" for p, v in topics.items() for x in v["methods"] + v["concepts"] if x not in voc]
    bad += [f"{s}: not in the inventory" for s in sensors if s not in src.inv]
    if bad:
        raise SystemExit("\n".join(bad))

    by_author_year = defaultdict(list)
    for k, d in docs.items():
        by_author_year[(lit.surname(works.get(k, {}), d).lower(), d.get("publication_year"))].append(k)

    def cite(pid: str) -> str:
        d, w = docs[pid], works.get(pid, {})
        name, year = lit.surname(w, d), d.get("publication_year")
        etal = " et al." if len(w.get("resolved_authors") or []) != 1 else ""
        hint = " on " + " ".join((d.get("title") or "").split()[:6]) if len(by_author_year[(name.lower(), year)]) > 1 else ""
        return f"{name}{etal} ({year}){hint}"

    def paper(pid: str) -> dict:
        return {"paper": pid, "cite": cite(pid), "title": docs[pid].get("title"), "doi": docs[pid].get("doi")}

    def under(entry: str, root: str) -> bool:   # entry is root or one of its descendants
        while entry:
            if entry == root:
                return True
            entry = voc[entry].get("parent")
        return False

    def term(eid: str) -> dict:
        return {"id": eid, "name": voc[eid]["name"]}

    scope = f"the {len(topics)} papers judged in authored/paper_topics.json"
    rows = []

    def q(t, entity, group, question, gold, kind):
        rows.append({"type": t, "type_name": TYPE_NAMES[t], "entity": entity, "group": group, "question": question,
                     "gold": gold, "gold_kind": kind, "source": "authored_links"})

    # 2: papers that used / mention a sensor.
    for sid, v in sensors.items():
        name = gen.names(src, sid)
        short = name[2] if len(name) > 2 and re.fullmatch(r"[A-Z]{3,4}\d{1,2}", name[2] or "") else name[0]
        refdes = f" ({name[1]})" if len(name) > 1 and re.fullmatch(r"(?:RS|CE)\w+-\w+-\w+-\w+", name[1]) else ""
        gold = {"used": [paper(p) for p in v["used"]], "mentioned": [paper(p) for p in v["mentioned"]]}
        for text in gen.pick([f"Which papers used data from {name[0]}?", f"what papers have analyzed {short} data",
                              f"Which papers used {short}, and which only mention it?",
                              f"list the publications that use the {name[0]}{refdes}"], sid, "2"):
            q(2, sid, src.area_of(sid) or "fiber", text, gold, "paper_used_mentioned")

    # 3 and 4: a paper's methods and concepts.
    for pid, v in topics.items():
        c = cite(pid)
        if v["methods"]:
            for text in gen.pick([f"What methods does {c} use?", f"which techniques did {c} apply",
                                  f"How did {c} analyze their data? Name the methods."], pid, "3", n=1):
                q(3, pid, "papers", text, {**paper(pid), "terms": [term(m) for m in v["methods"]]}, "term_set")
        if v["concepts"]:
            for text in gen.pick([f"What does {c} study?", f"what topics or features is {c} about",
                                  f"Which processes or features does {c} investigate?"], pid, "4", n=1):
                q(4, pid, "papers", text, {**paper(pid), "terms": [term(x) for x in v["concepts"]]}, "term_set")

    # 4 reversed: the papers that study a concept (its children included).
    for cid, e in voc.items():
        if e["kind"] != "concept":
            continue
        ps = sorted(p for p, v in topics.items() if any(under(x, cid) for x in v["concepts"]))
        if len(ps) < 2:
            continue
        for text in gen.pick([f"Which papers study {e['name'].lower()}?", f"papers about {e['name'].lower()}",
                              f"What research has been published on {e['name'].lower()}?"], cid, "4r", n=1):
            q(4, f"concept:{cid}", e["group"], text, {"papers": [paper(p) for p in ps], "scope": scope}, "paper_set")

    # 5: the papers about a site.
    for code, (entity, words) in SITE_ENTITY.items():
        takes = SITE_TAKES.get(code, {code})
        ps = sorted(p for p, v in topics.items() if takes & set(v["sites"]))
        if len(ps) < 2:
            continue
        for text in gen.pick([f"Which papers are about {words[0]}?", f"what research has been done at {words[1]}",
                              f"List the publications that study {words[0]}."], code, "5"):
            q(5, f"site_papers:{entity}", "sites", text, {"papers": [paper(p) for p in ps], "scope": scope}, "paper_set")

    # 8: the methods applied to a sensor's data, from the papers that used it.
    for sid, v in sensors.items():
        by = defaultdict(list)
        for p in v["used"]:
            for m in topics.get(p, {}).get("methods", []):
                by[m].append(p)
        if not by:
            continue
        name = gen.names(src, sid)
        short = name[2] if len(name) > 2 and re.fullmatch(r"[A-Z]{3,4}\d{1,2}", name[2] or "") else name[-1].removeprefix("the ")
        gold = {"terms": [{**term(m), "papers": [paper(p) for p in ps]} for m, ps in sorted(by.items())]}
        for text in gen.pick([f"What methods have been applied to {name[0]} data?", f"how have people analyzed data from {short}",
                              f"Which analysis techniques have papers used on {name[1] if len(name) > 1 else name[0]}?"], sid, "8", n=1):
            q(8, sid, src.area_of(sid) or "fiber", text, gold, "term_set_with_papers")

    # 9: the papers that did a method with RCA data (or RCA products such as its catalog).
    for mid, e in voc.items():
        if e["kind"] != "method":
            continue
        ps = sorted(p for p, v in topics.items() if v["rca"] != "none" and any(under(m, mid) for m in v["methods"]))
        if not ps:
            continue
        for text in gen.pick([f"Which papers did {e['name'].lower()} using RCA data?", f"who has applied {e['name'].lower()} to Regional Cabled Array data",
                              f"List the studies that used {e['name'].lower()} on OOI cabled array data."], mid, "9"):
            q(9, f"method:{mid}", e["group"], text, {"papers": [paper(p) for p in ps], "scope": scope,
                                                      "products_only": [p for p in ps if topics[p]["rca"] == "products"]}, "paper_set")

    # Split. Sensors and sites: as generate_source_questions.py splits them.
    gen_rows = gen.generate(src)
    def gen_area(e):
        if e in src.inv:
            return src.area_of(e)
        kind, code = e.split(":", 1)
        return "platforms" if kind in ("platform", "node") else code
    gen_entities = {r["entity"]: gen_area(r["entity"]) for r in gen_rows}
    split = gen.split_of(gen_entities, gen.seen_entities(src, list(gen_entities), HERE / "question_bank.jsonl"))
    # Papers in the literature questions: as build_literature_questions.py splits them (its train file names them).
    lit_papers = {e["paper"] for p in (HERE / "authored").glob("literature_batch*.json") for e in json.loads(p.read_text())}
    lit_train = {json.loads(l)["entity"] for l in (HERE / "literature_train.jsonl").read_text().splitlines() if l.strip()}
    for p in lit_papers:
        split.setdefault(p, "train" if p in lit_train else "blind")
    # The rest: train if a past question names them, else alternated by hash within their group.
    asked = "\n".join(json.loads(l)["question"] for l in (HERE / "question_bank.jsonl").read_text().splitlines() if l.strip())
    seen_papers = {r["gold"]["paper"] for l in (HERE / "question_bank.jsonl").read_text().splitlines() if l.strip()
                   for r in [json.loads(l)] if r["gold_kind"] == "paper_facts"}
    rest = defaultdict(list)
    for r in rows:
        e = r["entity"]
        if e in split or any(x["entity"] == e for x in rest[r["group"]]):
            continue
        seen = e in seen_papers
        if e.startswith("site_papers:"):   # a past question asking for the papers about this site
            words = [w for c, (ent, ws) in SITE_ENTITY.items() if ent == e.split(":", 1)[1] for w in ws]
            seen = any(re.search(rf"(?:paper|publication|stud|research|literature)[^\n]*{re.escape(w.removeprefix('the '))}|"
                                 rf"{re.escape(w.removeprefix('the '))}[^\n]*(?:paper|publication|literature)", asked, re.I) for w in words)
        if e.startswith(("concept:", "method:")):
            v = voc[e.split(":", 1)[1]]
            seen = bool(re.search(v["pattern"], asked, re.I if v["ignore_case"] else 0))
        if seen:
            split[e] = "train"
        else:
            rest[r["group"]].append({"entity": e})
    for group, es in rest.items():
        for i, x in enumerate(sorted(es, key=lambda x: h(x["entity"]))):
            split[x["entity"]] = "train" if i % 2 == 0 else "blind"

    for r in rows:
        r["split"] = split[r["entity"]]
        r["id"] = f"link:{r['type']}:{h(r['entity'], r['question']) % 10**8:08d}"
    args.blind.parent.mkdir(parents=True, exist_ok=True)
    for path, part in ((args.train, "train"), (args.blind, "blind")):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if r["split"] == part), encoding="utf-8")
    count = defaultdict(lambda: defaultdict(int))
    for r in rows:
        count[f"{r['type']} {r['type_name']}"][r["split"]] += 1
    print(json.dumps({"questions": len(rows), "entities": len({r["entity"] for r in rows}),
                      "by_type": {k: dict(v) for k, v in sorted(count.items())}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
