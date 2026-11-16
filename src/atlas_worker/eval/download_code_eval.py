"""Can Ask Atlas give working Python to download each instrument's data? One question a sensor, naming it and a
timeframe its easiest route was tested on (runtime_data/DataRecipes/tests.json, so the data exist): "Give me Python
code to download <name> (<designator>) data from <start> to <end> UTC". The deployed Worker answers; the script in the
answer runs in the recipe sandbox (src/data_recipes/test_recipes.py: no host folder, capped memory, CPU and work folder)
and passes when it exits cleanly having written a data file that is not empty. Also checked: whether the answer has a
script at all, whether the script carries the asked dates, and which service it reads (against the recipe's easiest).
Instruments whose only route is OOI M2M are left out (it needs an account, and queues each request).
Usage: python3 download_code_eval.py [--model ooi-gemma-4-26b] [--jobs 3] [--out results.json] [sensor ids...]"""
import argparse, json, re, sys, time, urllib.request
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/data_recipes"))
import test_recipes   # noqa: E402

WORKER = "https://rca-atlas.quakehunt.workers.dev/v1/answer"
TESTS = ROOT / "runtime_data/DataRecipes/tests.json"
SENSORS = ROOT / "src/atlas_map/public/atlas/sensors.json"
SERVICES = OrderedDict([("earthscope", r"service\.earthscope\.org|fdsn"), ("erddap", r"erddap"), ("gold", r"thredds|dodsC|opendap"),
                        ("raw", r"rawdata\.oceanobservatories"), ("portal", r"piweb\.ooirsn"), ("github", r"github"),
                        ("m2m", r"ooinet\.oceanobservatories\.org/api")])


def cases() -> list[dict]:
    """Each sensor's easiest tested route (the first of its tests, which are in the recipe's order) and its window."""
    sensors = json.loads(SENSORS.read_text())
    by_id = {s["id"]: s for s in (sensors["sensors"] if isinstance(sensors, dict) else sensors)}
    first = OrderedDict()
    for t in json.loads(TESTS.read_text()):
        first.setdefault(t["id"].split("#")[0], t)
    out = []
    for sid, t in first.items():
        s = by_id.get(sid)
        if not s or t["kind"] == "m2m" or not t.get("start"):
            continue
        a, b = (datetime.fromisoformat(t[k].replace("Z", "")) for k in ("start", "end"))
        if b - a < timedelta(minutes=10):   # EarthScope's one-minute checks: ask for ten minutes
            b = a + timedelta(minutes=10)
        label = s.get("refdes") or sid
        out.append({"id": sid, "name": s["name"], "label": label, "route": t["kind"], "start": a, "end": b,
                    "question": f"Give me Python code to download {s['name']} ({label}) data from "
                                f"{a:%Y-%m-%d %H:%M} to {b:%Y-%m-%d %H:%M} UTC"})
    return out


def ask(question: str, model: str) -> dict:
    req = urllib.request.Request(WORKER, data=json.dumps({"query": question, "model": model}).encode(),
                                 headers={"origin": "https://coszo.org", "content-type": "application/json", "user-agent": "curl/8.0 atlas-eval"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except Exception as e:   # noqa: BLE001
            err = str(e)
            time.sleep(10 * (attempt + 1))
    return {"error": err}


def grade(case: dict, answer: dict, img: str) -> dict:
    text = answer.get("answer") or ""
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    row = {"id": case["id"], "question": case["question"], "easiest": case["route"], "model": answer.get("answer_model"),
           "error": answer.get("error")}
    if not blocks:
        return {**row, "has_code": False, "passed": False}
    code = max(blocks, key=len)
    # A date as "2026-10-27" or as datetime(2026, 10, 27, ...).
    has = lambda d: f"{d:%Y-%m-%d}" in code or re.search(rf"\b{d.year},\s*0?{d.month},\s*0?{d.day}\b", code) is not None
    used = [k for k, pat in SERVICES.items() if re.search(pat, code, re.I)]
    run = test_recipes.run({"id": f"gemma-{case['id']}", "kind": "gemma", "code": code}, img)
    return {**row, "has_code": True, "dates_in_code": has(case["start"]) and has(case["end"]), "services": used,
            "same_route": case["route"] in used, "passed": run["passed"], "wrote": run.get("wrote"),
            "run_error": run.get("error"), "code": code}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ooi-gemma-4-26b")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--pause", type=float, default=3, help="seconds between questions")
    ap.add_argument("--out", default=str(Path(__file__).with_name("download_code_results.json")))
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args()
    todo = [c for c in cases() if not args.ids or c["id"] in args.ids]
    img = test_recipes.image()
    results, futures = [], []
    print(f"{len(todo)} sensors, model {args.model}", flush=True)
    with ThreadPoolExecutor(args.jobs) as pool:
        for i, case in enumerate(todo, 1):
            answer = ask(case["question"], args.model)      # questions one at a time; scripts run alongside
            futures.append(pool.submit(grade, case, answer, img))
            print(f"[{i}/{len(todo)}] asked {case['id']}", flush=True)
            time.sleep(args.pause)
        for f in futures:
            r = f.result()
            results.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'} {r['id']}: " + (r.get("wrote") or r.get("run_error") or r.get("error")
                  or ("no code" if not r["has_code"] else "")), flush=True)
    passed = sum(r["passed"] for r in results)
    summary = {"model": args.model, "asked": len(results), "passed": passed,
               "has_code": sum(r["has_code"] for r in results),
               "dates_in_code": sum(bool(r.get("dates_in_code")) for r in results),
               "same_route": sum(bool(r.get("same_route")) for r in results),
               "by_route": {k: f"{sum(r['passed'] for r in results if r['easiest'] == k)}/{n}"
                            for k, n in Counter(r["easiest"] for r in results).items()}}
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=1, default=str))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
