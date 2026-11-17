#!/usr/bin/env python3
"""Scores the literature links (build_literature_links.py's output) against the link questions' gold, with no model:
how many of each question's gold papers or terms the graph links, and how many it links that the gold does not have.
This tells how good the graph is before any answer is written; the evals with the Worker test the answers.

Types: 2 papers that used a sensor (and those only mentioning it), 3/4 a paper's methods and concepts, 4 the papers on a
concept, 5 the papers about a site, 8 the methods applied to a sensor's data, 9 the papers that did a method with RCA
data. Paper sets for 3/4/5/9 cover only the judged papers (gold "scope"): a linked paper outside them is not counted
against the graph. Development uses --split train; the blind half is scored once, at the end.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--links", type=Path, default=ROOT / "data/LiteratureLinks")
    parser.add_argument("--split", choices=["train", "blind"], default="train")
    parser.add_argument("--show", action="store_true", help="List each question's misses and extras.")
    args = parser.parse_args()
    path = HERE / ("links_train.jsonl" if args.split == "train" else "blind/links_blind.jsonl")
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    judged = set(json.loads((HERE / "authored/paper_topics.json").read_text())) - {"_rule"}

    rel = defaultdict(lambda: defaultdict(set))   # predicate -> source -> targets
    inv = defaultdict(lambda: defaultdict(set))   # predicate -> target -> sources
    parent = {}
    rca = set()
    for line in (args.links / "relationships.jsonl").read_text().splitlines():
        r = json.loads(line)
        rel[r["predicate"]][r["source_id"]].add(r["target_id"])
        inv[r["predicate"]][r["target_id"]].add(r["source_id"])
        if r["predicate"] == "NARROWER_THAN":
            parent[r["source_id"]] = r["target_id"]
    for line in (args.links / "entities.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e.get("uses_rca_data"):
            rca.add(e["entity_id"])

    def under(x, root):
        while x:
            if x == root:
                return True
            x = parent.get(x)
        return False

    def ancestors(x):
        out = []
        while x in parent:
            x = parent[x]
            out.append(x)
        return out

    term_id = lambda kind, t: ("METHOD-" if kind == 3 else "CONCEPT-") + t["id"]
    site_id = {"Axial Seamount": "SITE-axial-seamount", "the ASHES vent field": "SITE-ashes", "the Axial Central Caldera":
               "SITE-axial-central-caldera", "Axial Base": "SITE-axial-base", "Southern Hydrate Ridge": "SITE-southern-hydrate-ridge",
               "Oregon Slope Base": "SITE-oregon-slope-base", "Oregon Shelf": "SITE-oregon-shelf", "Oregon Offshore": "SITE-oregon-offshore"}
    tally = defaultdict(lambda: [0, 0, 0, 0])   # found gold, gold, linked in gold, linked (scored)
    seen_entity = set()
    for r in rows:
        t, e, g = r["type"], r["entity"], r["gold"]
        key = (t, e, json.dumps(g, sort_keys=True)[:200])
        if key in seen_entity:
            continue   # one score per entity and gold, not per phrasing
        seen_entity.add(key)
        if t == 2:
            want = {p["paper"] for p in g["used"]}
            mention = {p["paper"] for p in g["mentioned"]}
            got = inv["USES_SENSOR"][e]
            got_m = inv["MENTIONS_SENSOR"][e]
            name = f"2 used {e}"
            hits, extra = want & got, got - want
            tally["2 used"][0] += len(hits); tally["2 used"][1] += len(want)
            tally["2 used"][2] += len(hits); tally["2 used"][3] += len(got)
            tally["2 used→mention"][0] += len(want & got_m); tally["2 used→mention"][1] += len(want)
            tally["2 mention linked"][0] += len(mention & (got | got_m)); tally["2 mention linked"][1] += len(mention)
            tally["2 mention judged used"][0] += len(mention & got); tally["2 mention judged used"][1] += len(mention)
            if args.show and (want - got or extra):
                print(name, "missed", sorted(want - got), "extra", sorted(extra)[:12])
        elif t in (3, 4) and not e.startswith("concept:"):
            gold = {term_id(t, x) for x in g["terms"]}
            closure = gold | {a for x in gold for a in ancestors(x)}
            pred = rel["APPLIES_METHOD" if t == 3 else "STUDIES_CONCEPT"][e]
            found = {x for x in gold if x in pred or any(under(p, x) for p in pred)}
            k = f"{t} paper's {'methods' if t == 3 else 'concepts'}"
            tally[k][0] += len(found); tally[k][1] += len(gold); tally[k][2] += len(pred & closure); tally[k][3] += len(pred)
            if args.show and (gold - found):
                print(k, e, "missed", sorted(gold - found), "extra", sorted(pred - closure))
        else:
            want = {p["paper"] for p in g.get("papers", [])}
            if t == 4:
                target = "CONCEPT-" + e.split(":", 1)[1]
                got = {p for x, ps in inv["STUDIES_CONCEPT"].items() if under(x, target) for p in ps}
            elif t == 5:
                site = e.split(":", 1)[1]
                target = site_id.get(site)
                if "Hydrate Ridge" in r["question"] and "Southern" not in r["question"] and "southern" not in r["question"]:
                    target = "SITE-hydrate-ridge"
                got = {p for x, ps in inv["ABOUT_SITE"].items() if under(x, target) for p in ps}
            elif t == 9:
                target = "METHOD-" + e.split(":", 1)[1]
                got = {p for x, ps in inv["APPLIES_METHOD"].items() if under(x, target) for p in ps} & rca
            else:   # 8: methods applied to a sensor's data
                gold_terms = {"METHOD-" + x["id"] for x in g["terms"]}
                users = inv["USES_SENSOR"][e]
                pred = {m for p in users for m in rel["APPLIES_METHOD"][p]}
                closure = gold_terms | {a for x in gold_terms for a in ancestors(x)}
                found = {x for x in gold_terms if x in pred or any(under(p, x) for p in pred)}
                tally["8 sensor's methods"][0] += len(found); tally["8 sensor's methods"][1] += len(gold_terms)
                tally["8 sensor's methods"][2] += len(pred & closure); tally["8 sensor's methods"][3] += len(pred)
                if args.show and gold_terms - found:
                    print("8", e, "missed", sorted(gold_terms - found))
                continue
            scored = got & judged
            k = {4: "4 papers on a concept", 5: "5 papers about a site", 9: "9 papers doing a method (RCA)"}[t]
            tally[k][0] += len(want & got); tally[k][1] += len(want); tally[k][2] += len(scored & want); tally[k][3] += len(scored)
            if args.show and (want - got):
                print(k, e, "missed", sorted(want - got), "extra", sorted(scored - want)[:10])
    print(f"split {args.split}, links {args.links}")
    for k, (f, n, ok, linked) in sorted(tally.items()):
        line = f"{k:28s} recall {f}/{n} = {f / n:.2f}" if n else f"{k:28s} (no gold)"
        if linked:
            line += f"   precision {ok}/{linked} = {ok / linked:.2f}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
