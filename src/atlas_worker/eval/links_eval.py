"""The literature-link questions (src/question_bank: types 2, 3, 4, 5, 8 and 9) asked of Ask Atlas and scored against
their gold. Two modes:

- --evidence: runs the Worker's answer path locally against a Graph-RAG API (evidence_prompts.mjs, model stubbed) and
  checks that each gold paper or term reaches the prompt: what the model could answer from.
- default: asks the deployed Worker (Gemma, --model ooi-gemma-4-26b) and checks the answers: gold papers named (for
  type 2, under the papers that used the sensor and not under those mentioning it), gold terms named, and papers named
  that the gold does not have (counted only among the judged papers: the paper sets cover those).

A paper counts as named when the answer gives the start of its title, or its first author and year (when no other
judged paper shares them). A term counts when the answer uses its name or the vocabulary's words for it.
Development uses --split train; the blind half is run once, at the end.
Usage: python3 links_eval.py [--split train|blind] [--evidence API_ORIGIN] [--model ooi-gemma-4-26b] [--types 2,9]
       [--out results.json] [question ids...]"""
import argparse, json, os, re, subprocess, sys, tempfile, time, urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src/question_bank"))
import build_literature_questions as lit   # noqa: E402

WORKER = "https://rca-atlas.quakehunt.workers.dev/v1/answer"
norm = lambda t: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(t or "").lower().replace("‐", "-"))).strip()


def load_papers():
    docs = {json.loads(l)["document_id"]: json.loads(l) for l in (ROOT / "data/Literature/documents.jsonl").read_text().splitlines() if l.strip()}
    works = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/Literature/literature.jsonl").read_text().splitlines() if l.strip()}
    return docs, works


def paper_matchers(ids, docs, works):
    """paper id -> function(answer) -> bool."""
    key = {}
    for pid in ids:
        d = docs.get(pid, {})
        key[pid] = (lit.surname(works.get(pid, {}), d).lower(), d.get("publication_year"))
    shared = defaultdict(int)
    for k in key.values():
        shared[k] += 1
    out = {}
    for pid in ids:
        title = norm(docs.get(pid, {}).get("title")).split()
        start = " ".join(title[:6]) if len(title) >= 3 else None
        surname, year = key[pid]
        by_author = re.compile(rf"\b{re.escape(norm(surname))}\b[^.\n]{{0,80}}?\b{year}\b") if shared[key[pid]] == 1 and year else None
        out[pid] = lambda answer, start=start, by_author=by_author: bool(
            (start and start in norm(answer)) or (by_author and by_author.search(norm(answer))))
    return out


def split_used(answer):
    """The part of a type 2 answer listing papers that used the sensor, and the part listing mentions."""
    m = re.search(r"^[^\n]*(?:papers?|studies|publications?)\s+(?:that\s+)?(?:only\s+)?mention", answer, re.I | re.M)
    return (answer[:m.start()], answer[m.start():]) if m else (answer, "")


def ask(question, model):
    body = {"query": question, **({"model": model} if model else {})}
    req = urllib.request.Request(WORKER, json.dumps(body).encode(), {"content-type": "application/json", "origin": "https://coszo.org",
                                                                      "user-agent": "curl/8.0 atlas-eval"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=240)).get("answer") or ""
    except Exception as error:
        return f"ERROR {error}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["train", "blind"], default="train")
    ap.add_argument("--evidence", metavar="API_ORIGIN")
    ap.add_argument("--model", default="ooi-gemma-4-26b")
    ap.add_argument("--types", default="2,3,4,5,8,9")
    ap.add_argument("--out", type=Path)
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args()
    path = ROOT / "src/question_bank" / ("links_train.jsonl" if args.split == "train" else "blind/links_blind.jsonl")
    types = {int(t) for t in args.types.split(",")}
    rows = [r for r in map(json.loads, path.read_text().splitlines()) if r["type"] in types and (not args.ids or r["id"] in args.ids)]
    vocab = {("METHOD-" if e["kind"] == "method" else "CONCEPT-") + e["id"]: e for e in json.loads((ROOT / "src/literature_links/vocabulary.json").read_text())}
    judged = set(json.loads((ROOT / "src/question_bank/authored/paper_topics.json").read_text())) - {"_rule"}
    docs, works = load_papers()
    gold_ids = {p["paper"] for r in rows for k in ("used", "mentioned", "papers") for p in r["gold"].get(k, [])}
    match = paper_matchers(sorted(judged | gold_ids), docs, works)

    if args.evidence:   # the prompts the local Worker builds, with the model stubbed
        with tempfile.TemporaryDirectory() as tmp:
            qpath, opath = Path(tmp) / "q.json", Path(tmp) / "o.json"
            qpath.write_text(json.dumps([{"id": r["id"], "question": r["question"]} for r in rows]))
            env = {**os.environ}
            if "ATLAS_API_KEY" not in env:
                env["ATLAS_API_KEY"] = next(l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text().splitlines() if l.startswith("GRAPHRAG_API_KEY="))
            subprocess.run(["node", str(HERE / "evidence_prompts.mjs"), args.evidence, str(qpath), str(opath)], env=env, check=True,
                           stderr=subprocess.DEVNULL)
            texts = {o["id"]: o["prompt"] or f"ERROR {o.get('error')}" for o in json.loads(opath.read_text())}
    else:
        texts = {}
        for r in rows:
            texts[r["id"]] = ask(r["question"], args.model)
            time.sleep(2)

    tally = defaultdict(lambda: [0, 0, 0, 0])   # gold found, gold, extra judged papers named, questions
    out = []
    for r in rows:
        text, g, t = texts.get(r["id"], ""), r["gold"], r["type"]
        result = {"id": r["id"], "type": t, "question": r["question"]}
        if t == 2:
            used_part, mention_part = split_used(text) if not args.evidence else (text, text)
            want = [p["paper"] for p in g["used"]]
            found = [p for p in want if match[p](used_part)]
            wrongly_used = [p["paper"] for p in g["mentioned"] if match[p["paper"]](used_part)] if not args.evidence else []
            extra = [p for p in judged if p not in want and p not in {x["paper"] for x in g["mentioned"]} and match[p](used_part)]
            k = "2 used" + (" (none in gold)" if not want else "")
            tally[k][0] += len(found); tally[k][1] += len(want); tally[k][2] += len(extra) + len(wrongly_used); tally[k][3] += 1
            result.update(missed=[p for p in want if p not in found], mention_as_used=wrongly_used, extra=extra)
        elif "terms" in g:
            want = [x["id"] for x in g["terms"]]
            ids = [("METHOD-" if t in (3, 8) else "CONCEPT-") + i for i in want]
            def named(i):
                e = vocab.get(i)
                return bool(e and (norm(e["name"]) in norm(text) or re.search(e["pattern"], text, re.I if e["ignore_case"] else 0)))
            found = [w for w, i in zip(want, ids) if named(i)]
            k = {3: "3 paper's methods", 4: "4 paper's concepts", 8: "8 sensor's methods"}[t]
            tally[k][0] += len(found); tally[k][1] += len(want); tally[k][3] += 1
            result.update(missed=[w for w in want if w not in found])
        else:
            want = [p["paper"] for p in g["papers"]]
            found = [p for p in want if match[p](text)]
            extra = [p for p in judged if p not in want and match[p](text)]
            k = {4: "4 papers on a concept", 5: "5 papers about a site", 9: "9 papers doing a method"}[t]
            tally[k][0] += len(found); tally[k][1] += len(want); tally[k][2] += len(extra); tally[k][3] += 1
            result.update(missed=[p for p in want if p not in found], extra=extra)
        if not args.evidence:
            result["answer"] = text
        out.append(result)
        print(f"{r['id']} t{t} found {len(want) - len(result['missed'])}/{len(want)}"
              + (f" extra {len(result.get('extra', []))}" if result.get("extra") else "")
              + (f" mention-as-used {len(result['mention_as_used'])}" if result.get("mention_as_used") else ""), flush=True)
    print(f"\n{'evidence' if args.evidence else 'answers'} ({args.split})")
    for k, (f, n, extra, q) in sorted(tally.items()):
        print(f"{k:28s} {q:3d} questions  gold found {f}/{n} = {f / n:.2f}" if n else f"{k:28s} {q:3d} questions  (no gold papers)",
              f" judged papers named beyond the gold {extra}" if t != 3 else "")
    if args.out:
        args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
