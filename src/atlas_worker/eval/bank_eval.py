"""The question bank (src/question_bank) asked of Ask Atlas, every type but the literature links (links_eval.py has
those), each answer scored against its key:

- facts (types 7, 11, 12, 13, 14, generated from OOI asset management, StationXML and the SCPR's log): each value the
  key holds must be in the answer (a serial, a maker, a depth within 2%, a date written any common way, a count, that
  the record is ongoing, whether a seismometer is misoriented);
- sensor_set (type 6) and station_set (type 13): the share of the key's sensors or stations the answer names;
- paper_facts (type 1) and paper_summary (type 10): each fact's pattern, and for a summary at least min_facts of them;
- paper_title_regex and relevant_chunk_regex (questions asked in past sessions): the pattern in the answer.
Keys that are prose (reference_answer), point at another eval (computed_from_sources, script_runs) or are empty are
not scored here; they are counted.

Default: the deployed Worker with Gemma, three questions at a time, one phrasing per entity. --evidence API_ORIGIN
checks the prompt the local Worker builds instead (model stubbed). Development uses train; blind runs once.
Usage: python3 bank_eval.py [--split train|blind] [--evidence API_ORIGIN] [--types 6,7] [--all-phrasings] [--out f.json]"""
import argparse, json, os, re, subprocess, sys, tempfile, time, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BANK = ROOT / "src/question_bank"
WORKER = "https://rca-atlas.quakehunt.workers.dev/v1/answer"
MONTHS = "January February March April May June July August September October November December".split()


def plain(text):
    return str(text or "").translate({0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x00a0: " ", 0x202f: " ", 0x2009: " "})


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.]+", " ", plain(text).lower())).strip()


def date_rx(day):
    """A date as an answer may write it: 2021-08-28, August 28, 2021, 28 August 2021, Aug 28 2021."""
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    mon = MONTHS[m - 1]
    return rf"{day[:10]}|{mon[:3]}\w*\.?\s+{d},?\s+{y}|\b{d}\s+{mon[:3]}\w*\.?,?\s+{y}|{y}/{m:02d}/{d:02d}"


def number_near(text, value, tol):
    return any(abs(float(n.replace(",", "")) - value) <= tol for n in re.findall(r"\d[\d,]*\.?\d*", text) if n.replace(",", "").replace(".", "").isdigit())


def found(rx, text):
    return bool(re.search(rx, plain(text), re.I))


def sensor_names(inv):
    """sensor id -> the ways an answer may name it: station code, designators, name."""
    out = {}
    for sid, d in inv.items():
        ways = [n for n in [d.get("name"), *(d.get("aliases") or [])] if n and len(n) >= 5]
        m = re.fullmatch(r"EARTHSCOPE-OO-([A-Z0-9]+)", sid)
        if m:
            ways.append(m.group(1))
        if re.fullmatch(r"(?:RS|CE)\w+-\w+-\w+-\w+", sid):
            ways += [sid, sid.split("-")[-1]]
        out[sid] = ways
    return out


def score(row, text, names):   # noqa: C901
    """(facts found, facts asked, notes) for one answer; None when the key cannot be scored here."""
    g, kind, t = row.get("gold"), row.get("gold_kind"), row["type"]
    if kind == "facts":
        checks = []
        if "current_serial" in g:
            checks.append(("serial " + g["current_serial"], found(rf"\b{re.escape(g['current_serial'])}\b", text)))
        if "manufacturer" in g:
            checks.append(("maker " + g["manufacturer"], norm(g["manufacturer"]).split()[0] in norm(text)))
        if g.get("model"):
            words = [w for w in norm(g["model"]).split() if len(w) >= 4][:2]
            checks.append(("model " + g["model"], bool(words) and all(w in norm(text) for w in words)))
        if "depth_m" in g and g["depth_m"] is not None:
            checks.append((f"depth {g['depth_m']} m", number_near(plain(text), float(g["depth_m"]), max(2.0, 0.02 * float(g["depth_m"])))))
        # A changes question asks how often and with which serials; it needs the first date only when it asks when.
        asks_when = t != 12 or re.search(r"\b(?:when|since|first|start|date)\b", row["question"], re.I)
        if "first_deployed" in g and g["first_deployed"] and asks_when:
            checks.append(("first " + g["first_deployed"], found(date_rx(g["first_deployed"]), text)))
        if "ongoing" in g:
            if g["ongoing"]:
                checks.append(("ongoing", found(r"ongoing|present|current(?:ly)?|still|to date|to now|continu|operating|active", text)))
            elif g.get("last_ended"):
                checks.append(("ended " + g["last_ended"], found(date_rx(g["last_ended"]), text)))
        if "serials_in_order" in g:
            checks.append((f"{g['deployments']} deployments", found(rf"\b{g['deployments']}\b", text)))
            for s in g["serials_in_order"]:
                checks.append(("serial " + s["serial"], found(rf"\b{re.escape(s['serial'])}\b", text)))
        if "channels" in g:
            have = sum(found(rf"\b{re.escape(c.split('.')[-1])}\b", text) for c in g["channels"])
            checks.append((f"half of {len(g['channels'])} channels", have >= len(g["channels"]) / 2))
            checks.append(("first " + g["first"], found(date_rx(g["first"]), text)))
        if "azimuths" in g:
            issue = g["components_disagree"] or g["not_north"]
            said = found(r"misorient|not (?:correctly |properly )?(?:oriented|aligned)|rotated|disagree|inconsisten|orientation issue|off north", text)
            ok = found(r"correctly oriented|aligned (?:with|to) (?:true )?north|oriented (?:to|toward|towards) (?:true )?north|no orientation issue|0\s*°", text)
            checks.append(("misoriented" if issue else "oriented to north", said if issue else (ok and not said)))
        if "calibration_in_force" in g and g["calibration_in_force"]:
            checks.append(("calibration " + g["calibration_in_force"], found(date_rx(g["calibration_in_force"]), text)))
        if "last_calibration_start" in g:
            checks.append(("last calibration " + g["last_calibration_start"][:10], found(date_rx(g["last_calibration_start"][:10]), text)))
        return sum(ok for _, ok in checks), len(checks), [l for l, ok in checks if not ok]
    if kind == "sensor_set":
        want = g["sensors"]
        got = [s for s in want if any(re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", plain(text), re.I) for w in names.get(s, [s]))]
        return len(got), len(want), [s for s in want if s not in got][:12]
    if kind == "station_set":
        want = sorted(set(g["components_disagree"]) | set(g["not_north"]))
        got = [s for s in want if re.search(rf"\b{s}\b", text)]
        return len(got), len(want), [s for s in want if s not in got]
    if kind in ("paper_facts", "paper_summary"):
        facts = [(label, rx) for label, rx, *extra in g["facts"] if not extra]
        hits = [label for label, rx in facts if found(rx, text)]
        if kind == "paper_summary":
            need = min(g.get("min_facts", 2), len(facts))
            return int(len(hits) >= need), 1, [] if len(hits) >= need else [f"{len(hits)} of {need} key points"]
        return len(hits), len(facts), [l for l, _ in facts if l not in hits]
    if kind in ("paper_title_regex", "relevant_chunk_regex"):
        ok = found(g, text)
        return int(ok), 1, [] if ok else [g]
    return None


def ask(question, model):
    body = json.dumps({"query": question, "model": model}).encode()
    req = urllib.request.Request(WORKER, body, {"content-type": "application/json", "origin": "https://coszo.org", "user-agent": "curl/8.0 atlas-eval"})
    last = None
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=240)).get("answer") or ""
        except Exception as error:
            last = error
            time.sleep(10)
    return f"ERROR {last}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["train", "blind"], default="train")
    ap.add_argument("--evidence", metavar="API_ORIGIN")
    ap.add_argument("--model", default="ooi-gemma-4-26b")
    ap.add_argument("--types", default="1,6,7,10,11,12,13,14")
    ap.add_argument("--all-phrasings", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    types = {int(t) for t in args.types.split(",")}
    files = (["question_bank.jsonl", "generated_train.jsonl", "literature_train.jsonl"] if args.split == "train"
             else ["blind/generated_blind.jsonl", "blind/literature_blind.jsonl"])
    rows = [r for f in files for r in map(json.loads, (BANK / f).read_text().splitlines()) if r.get("type") in types]
    skipped = defaultdict(int)
    scorable = []
    inv = {json.loads(l)["canonical_id"]: json.loads(l) for l in (ROOT / "data/Instruments/instruments.jsonl").read_text().splitlines() if l.strip()}
    names = sensor_names(inv)
    for r in rows:
        if score(r, "", names) is None:
            skipped[r.get("gold_kind") or "no key"] += 1
        else:
            scorable.append(r)
    if not args.all_phrasings:
        seen = set()
        scorable = [r for r in scorable if r.get("entity") is None or not ((r["type"], r["entity"], json.dumps(r["gold"], sort_keys=True)[:300]) in seen
                    or seen.add((r["type"], r["entity"], json.dumps(r["gold"], sort_keys=True)[:300])))]
    print(f"{len(scorable)} questions to score; not scored here: {dict(skipped)}", flush=True)

    if args.evidence:
        with tempfile.TemporaryDirectory() as tmp:
            q, o = Path(tmp) / "q.json", Path(tmp) / "o.json"
            q.write_text(json.dumps([{"id": r.get("id") or str(i), "question": r["question"]} for i, r in enumerate(scorable)]))
            env = {**os.environ, "ATLAS_API_KEY": os.environ.get("ATLAS_API_KEY") or next(
                l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text().splitlines() if l.startswith("GRAPHRAG_API_KEY="))}
            subprocess.run(["node", str(HERE / "evidence_prompts.mjs"), args.evidence, str(q), str(o)], env=env, check=True, stderr=subprocess.DEVNULL)
            got = {x["id"]: x["prompt"] or f"ERROR {x.get('error')}" for x in json.loads(o.read_text())}
            texts = [got[r.get("id") or str(i)] for i, r in enumerate(scorable)]
    else:
        with ThreadPoolExecutor(args.workers) as pool:
            texts = list(pool.map(lambda r: ask(r["question"], args.model), scorable))

    tally = defaultdict(lambda: [0, 0, 0, 0, 0])   # facts found, facts, questions fully right, questions, errors
    out = []
    for r, text in zip(scorable, texts):
        f, n, missed = score(r, text, names)
        k = f"{r['type']:>2} {r.get('type_name') or r.get('gold_kind')} ({r.get('gold_kind')})"
        t = tally[k]
        t[0] += f; t[1] += n; t[2] += f == n; t[3] += 1; t[4] += text.startswith("ERROR")
        out.append({"id": r.get("id"), "type": r["type"], "question": r["question"], "found": f, "of": n, "missed": missed,
                    **({} if args.evidence else {"answer": text})})
    print(f"\n{'evidence' if args.evidence else 'answers'} ({args.split})")
    for k, (f, n, right, q, err) in sorted(tally.items()):
        print(f"{k:58s} {q:4d} questions  {right:4d} fully right  facts {f}/{n} = {f / n:.2f}" + (f"  errors {err}" if err else ""))
    if args.out:
        args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
