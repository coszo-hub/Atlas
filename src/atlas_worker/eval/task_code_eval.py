"""Can Ask Atlas write working code for the analysis tasks (src/task_recipes)? One live question per task, in a
person's words, with a station, place or time different from the recipe's own example, asked of the deployed Worker
(Gemma). The script in the answer runs unchanged in the recipe sandbox (src/data_recipes/test_recipes.py: no host
folder, capped memory, CPU and work folder) and passes when it exits cleanly having written a file (a figure or data)
that is not empty. Also checked: that the answer has a script, and that it carries what the question set (the
station, the dates). The DAS task is left out: its files are 1-2 GB, over the sandbox's cap.
Usage: python3 task_code_eval.py [--model ooi-gemma-4-26b] [--jobs 3] [--out results.json] [task ids...]"""
import argparse, json, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/data_recipes"))
import test_recipes   # noqa: E402

WORKER = "https://rca-atlas.quakehunt.workers.dev/v1/answer"
# (task, question, what the script must carry as the question set it). Each window has data (checked 17 Nov 2026): the
# first run asked for a hydrophone gap (12 Oct), a profiler CTD past its last data (Sept) and a CTD not on ERDDAP.
CASES = [
    ("earthquake_waveform", "Write Python code to plot the waveform at AXCC1 from 2026-10-20 03:10 to 03:14 UTC with the instrument response removed and a 4-30 Hz bandpass", [r"AXCC1", r"2026-10-20"]),
    ("seismic_noise_psd", "Write a script to compute the noise PSD of the AXEC2 seismometer for 2 days starting 1 October 2026", [r"AXEC2", r"2026-10-01|2026, 10, 1\b"]),
    ("sta_lta_detection", "Write code to detect earthquakes at Axial with STA/LTA on 5 October 2026 from 02:00 to 04:00 UTC", [r"2026-10-05"]),
    ("hydrophone_spectrogram", "Python code for a spectrogram of the Axial Base broadband hydrophone for 30 minutes from 2026-11-01 06:00 UTC", [r"2026-11-01|2026, 11, 1\b"]),
    ("axial_uplift", "Write code to plot Axial Seamount's uplift from March to October 2026 with uplift rates", [r"2026-03"]),
    ("profiler_ctd_section", "Python code for a T-S diagram and depth-time section from the Slope Base shallow profiler CTD for 10-14 August 2026", [r"2026-08-1[04]|2026, 8, 1[04]", r"rs01sbps"]),
    ("qc_time_series", "Write a script for daily mean temperature at the Slope Base seafloor CTD in 2025, without QARTOD failed data", [r"2025", r"rs01slbs"]),
    ("adcp_currents", "How do I plot current speed and direction from the Slope Base seafloor ADCP on 15 September 2026? Give me code", [r"2026-09-15", r"RS01SLBS"]),
    ("earthscope_availability", "Write code to find which days in October 2026 the Hydrate Ridge seismometers HYS11 to HYS14 had data", [r"HYS1", r"2026-10"]),
    ("erddap_coverage", "Write code showing which days the Slope Base deep profiler CTD has data on ERDDAP in 2023", [r"RS01SBPD", r"2023"]),
    ("event_waveform_package", "Write code to save the waveforms of M4.5 or larger earthquakes within 500 km of Axial in September 2026 at AXCC1 and AXAS1, response removed, as MiniSEED", [r"2026-09", r"AXCC1"]),
    ("botpt_detide", "Write code to remove the tides from the eastern caldera BOTPT pressure for August 2026, hour by hour", [r"BOTPTA302", r"2026-08"]),
    ("station_response", "Write code to list HYSB1's channels, epochs, orientations and instrument responses", [r"HYSB1"]),
    ("botpt_tilt", "Write code for the tilt at the International District BOTPT for September 2026, with relevels removed", [r"BOTPTA303", r"2026-09"]),
    ("vel3d_currents", "Write a script for cleaned currents and tides from the Slope Base VEL3D current meter, 1 to 15 August 2026", [r"RS01SLBS-MJ01A-12-VEL3DB101", r"2026-08"]),
    ("tmpsf_vent_temperature", "Write code to find which ASHES vent thermistors were warm in October 2026 and how they follow the tide", [r"2026-10"]),
]


def ask(question, model):
    body = json.dumps({"query": question, "model": model, "answer_mode": "code"}).encode()
    req = urllib.request.Request(WORKER, body, {"origin": "https://coszo.org", "content-type": "application/json", "user-agent": "curl/8.0 atlas-eval"})
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read())
        except Exception as e:   # noqa: BLE001
            err = str(e)
            time.sleep(10 * (attempt + 1))
    return {"error": err}


def grade(case, answer, img):
    task, question, carries = case
    text = answer.get("answer") or ""
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    row = {"task": task, "question": question, "model": answer.get("answer_model"), "error": answer.get("error")}
    if not blocks:
        return {**row, "has_code": False, "passed": False, "answer": text[:600]}
    code = max(blocks, key=len)
    run = test_recipes.run({"id": f"task-{task}", "kind": "gemma", "code": code}, img)
    return {**row, "has_code": True, "carries": [bool(re.search(c, code, re.I)) for c in carries],
            "passed": run["passed"], "wrote": run.get("wrote"), "run_error": run.get("error"), "code": code}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="ooi-gemma-4-26b")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", type=Path)
    ap.add_argument("tasks", nargs="*")
    args = ap.parse_args()
    cases = [c for c in CASES if not args.tasks or c[0] in args.tasks]
    img = test_recipes.image()
    with ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(lambda c: grade(c, ask(c[1], args.model), img), cases))
    for r in rows:
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['task']:24s} code={r['has_code']} carries={r.get('carries')} "
              f"{r.get('wrote') or r.get('run_error') or r.get('error') or ''}"[:220], flush=True)
    print(f"\n{sum(r['passed'] for r in rows)}/{len(rows)} of Gemma's task scripts ran and wrote their output; "
          f"{sum(r['has_code'] for r in rows)}/{len(rows)} answers had a script")
    if args.out:
        args.out.write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
