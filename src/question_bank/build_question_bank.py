#!/usr/bin/env python3
"""The question bank: every Ask Atlas question we have, tagged by question type, with its gold where it has one.

Sources: the questions asked in past sessions and quoted in commit messages (past_questions.json, extracted from the
session transcripts and git log), and the existing evals (literature_eval, literature_content_eval, shorthand_eval,
asset_eval, download_code_eval in src/atlas_worker/eval, and src/model_eval's rca_eval_v1). These have all been seen
and fixed against, so they are the train split; the blind split is built from new questions only (blind.jsonl, kept
apart).

Question types (the graph relation each tests):
  1 literature    a question answered from papers, citing them      8 method_sensor  methods applied to a sensor's data
  2 paper_sensor  papers that used / mention a sensor               9 method_papers  papers that did a method at the RCA
  3 paper_method  methods a paper applies                          10 paper_summary  about Author et al. (year)
  4 paper_concept concepts or features a paper studies             11 data_availability  date ranges, downloads
  5 site_papers   papers about a site                              12 changes        metadata changes, swaps, deployments
  6 site_sensors  sensors at a site                                13 errors         instrument errors (orientation issues)
  7 sensor_info   about a sensor: type, maker, serial, location    14 calibration    calibrations
  0 other         live status, earthquake counts, tasks
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "src/atlas_worker/eval"
HERE = Path(__file__).resolve().parent
TYPES = {1: "literature", 2: "paper_sensor", 3: "paper_method", 4: "paper_concept", 5: "site_papers", 6: "site_sensors",
         7: "sensor_info", 8: "method_sensor", 9: "method_papers", 10: "paper_summary", 11: "data_availability",
         12: "changes", 13: "errors", 14: "calibration", 0: "other"}

# Past questions that are about the app, the setup or our work, not questions for Ask Atlas.
NOT_ATLAS = re.compile(r"website|legend|button|marker|circle|pops up|status unknown next|download links|live data not|"
                       r"wrangler|secret put|OpenRouter|Gemma realize|kind of earthquake catalog questions|spread across|"
                       r"\{label\}|\{name\}|\{start\}|EarthScope says a station is|Nereus's live status|Nereus does not know|"
                       r"how many download scripts|added as a marker|live data is getting pulled|whale tracks|Can it answer|"
                       r"Are these meta data|can it answer|Answer temporarily|asset manangement|^Where to download$|"
                       r"\[showing|/ Try again|\.\.\.\s*\[|…\s*\[", re.I)


def classify(q: str) -> int:
    s = q.lower()
    papers = re.search(r"\b(papers?|stud(?:y|ies)|research|publications?|proposal|dataset has)\b", s)
    if re.search(r"calibrat", s) and not papers:
        return 14
    if re.search(r"orientation|oriented|azimuth|disoriented|misorient|misalign", s):
        return 13
    if re.search(r"swap|replaced|recovered|deploy(?:ed|ments?)\b.*(?:when|how many|first|last)|how many times|first deployed|"
                 r"last deployment|junction box|metadata change|has had", s):
        return 12
    if re.search(r"download|get (?:the )?\w* ?data|code to|script|where can i get|data (?:is )?available|date range|where is the \w*das", s):
        return 11
    if papers and re.search(r"interferometry|method|technique|machine learning|tomography", s) and not re.search(r"\b(hys|ax[a-z]{2}\d|botpt|seismomet|hydrophone|obs)\b", s):
        return 9
    if papers and re.search(r"\b(us(?:e|ed|es|ing)|data)\b", s) and re.search(r"\b(hys\d|ax[a-z]{2}\d|botpt|covis|seismomet|hydrophone|\bobs\b|sensor|prest|scpr|camhd)", s):
        return 2
    if re.search(r"tell me about .* et al|et al\.? \(?\d{4}", s):
        return 10
    if papers:
        return 1
    if re.search(r"serial|make and model|who makes|manufacturer|what does the \w+ measure|what is an? \w+ used|where is the scpr|"
                 r"location of the scpr|where was|what is the serial|deepest|what depth|how deep is the \w+ (?:sensor|adcp)", s):
        return 7
    if re.search(r"(which|what|list)\b.*\b(sensors?|instruments?|seismometers?|hydrophones?|stations?|gauges?|ctds?|vel3d)\b.*\b(at|are|in|of|part of|deployed)\b|"
                 r"what instruments|instruments at|depths were the hydrophones", s):
        return 6
    if re.search(r"working|operational|offline|how many earthquakes|fin whale calls|remove the jumps|plot the|qc'd", s):
        return 0
    return 1


# model_eval's own categories, by question type (and, for other, what kind).
MODEL_EVAL_TYPE = {"instrument_identity": 7, "instrument_location": 6, "data_availability": 11, "literature": 1,
                   "concepts": (0, "background"), "qaqc": (0, "qaqc"), "chronfix": (0, "clock_correction"),
                   "earthquakes": (0, "earthquake_catalog"), "operational_status": (0, "live_status"), "visual": (0, "figures"),
                   "graph_edges": (0, "graph_trace"), "tool_selection": (0, "tools"), "tool_avoidance": (0, "tools"), "full_text": 1}
MODEL_EVAL_ID_TYPE = {"instrument-005": 6, "location-001": 7, "location-002": 7, "location-004": (0, "graph_trace"),
                      "location-005": 12, "literature-004": 1}
# Past questions the rules type wrongly.
OVERRIDE = {
    "what is axial seamount": (0, "background"), "how do seismometers work?": (0, "background"), "where is axial seamount?": (0, "background"),
    "can 8hz data see earthquakes?": (0, "background"), "what does onc operate near the rca": (6, None),
    "where are the bprs deployed for coszo": (6, None), "where are the vel3d sensors at cascadia slope": (6, None),
    "which instrument is …ce04osbp…": (7, None), "what is the pn1b node used for": (7, None),
    "which cruise deployed the central caldera adcp?": (12, None), "what does the dts measure on the rca cables": (7, None),
    "is the pressure gauge at slope base operational": (0, "live_status"), "is the central caldera botpt working?": (0, "live_status"),
    "how many earthquakes at axial today?": (0, "earthquake_catalog"), "how many earthquakes at axial on 11-nov-2026": (0, "earthquake_catalog"),
    "how many fin whale calls at axial in december 2024?": (0, "fin_whale_counts"),
    "how do i remove the jumps in the x and y tilt of the axial caldera botpt?": (0, "task_code"),
    "how do i get a qc'd week of axial base bottom currents from the vel3d?": (0, "task_code"),
    "how do i plot the current speed and direction from the axial base adcp?": (0, "task_code"),
    "how many earthquakes occurs at axial seamount on october 1sr 2026": (0, "earthquake_catalog"),
    "what papers used the axec2 and axec1": (2, None), "which study used obs data at axial": (2, None),
    "which study used ci obs data offshore oregon": (1, None), "which study used ci obs data": (1, None),
    "which paper built a catalog of offshore seismicity in cascadia from ci obs data": (1, None),
}


def ast_cases(path: Path, name: str = "CASES") -> list:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            out = []
            for elt in node.value.elts:
                vals = [e.value if isinstance(e, ast.Constant) else (ast.literal_eval(e) if isinstance(e, (ast.List, ast.Tuple)) else getattr(e, "id", None))
                        for e in elt.elts]
                out.append(vals)
            return out
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--past", type=Path, required=True, help="past_questions.json (session transcripts and git log)")
    parser.add_argument("--out", type=Path, default=HERE / "question_bank.jsonl")
    args = parser.parse_args()
    rows, seen = [], set()

    def add(question, source, *, gold=None, gold_kind=None, ref=None, qtype=None, date=None):
        q = re.sub(r"\s+", " ", str(question)).strip().rstrip("\\").strip()
        key = re.sub(r"[^a-z0-9]", "", q.lower())
        if not q:
            return
        if key in seen:
            # Asked before and also an eval case: the eval's gold joins the earlier row.
            row = next(r for r in rows if re.sub(r"[^a-z0-9]", "", r["question"].lower()) == key)
            if gold is not None and row["gold"] is None:
                row.update(gold=gold, gold_kind=gold_kind, also_in=f"{source}:{ref or ''}")
            return
        seen.add(key)
        kind = None
        if q.lower() in OVERRIDE:
            t, kind = OVERRIDE[q.lower()]
        else:
            t = qtype if qtype is not None else classify(q)
        if isinstance(t, tuple):
            t, kind = t
        rows.append({"id": f"{source}:{ref or len(rows) + 1}", "type": t, "type_name": TYPES[t], "other_kind": kind,
                     "question": q, "source": source, "split": "train", "gold_kind": gold_kind, "gold": gold, "asked": date})

    for r in json.loads(args.past.read_text()):
        if not NOT_ATLAS.search(r["question"]):
            add(r["question"], "past_session" if r["date"] != "git" else "commit_log", date=None if r["date"] == "git" else r["date"])
    for q, pattern in ast_cases(EVAL / "literature_eval.py"):
        add(q, "literature_eval", gold=pattern, gold_kind="paper_title_regex", qtype=1)
    for q, pattern in ast_cases(EVAL / "shorthand_eval.py"):
        add(q, "shorthand_eval", gold=pattern, gold_kind="relevant_chunk_regex")
    for cid, paper, q, facts, abstract in ast_cases(EVAL / "literature_content_eval.py"):
        add(q, "literature_content_eval", ref=cid, gold={"paper": paper, "facts": facts, "from_abstract": abstract},
            gold_kind="paper_facts", qtype=1)
    for case in ast_cases(EVAL / "asset_eval.py"):
        cid, q = case[0], case[1]
        add(q, "asset_eval", ref=cid, gold=f"asset_eval.py:{case[2]}", gold_kind="computed_from_sources")
    add("Give me Python code to download {name} ({label}) data from {start} to {end} UTC", "download_code_eval", ref="template",
        gold="download_code_eval.py: one per instrument, the script is run in the sandbox", gold_kind="script_runs", qtype=11)
    golds = {json.loads(l)["question_id"]: json.loads(l) for l in (ROOT / "src/model_eval/datasets/rca_eval_v1_gold.jsonl").read_text().splitlines() if l.strip()}
    for line in (ROOT / "src/model_eval/datasets/rca_eval_v1.jsonl").read_text().splitlines():
        r = json.loads(line)
        g = golds.get(r["id"])
        add(r["question"], "model_eval", ref=r["id"], gold=g and {k: g[k] for k in ("reference_answer", "required_entity_ids") if k in g},
            gold_kind=g and "reference_answer", qtype=MODEL_EVAL_ID_TYPE.get(r["id"], MODEL_EVAL_TYPE.get(r["category"], 0)))

    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    by = {}
    for r in rows:
        by.setdefault((r["type"], r["type_name"]), []).append(r["source"])
    print(json.dumps({"questions": len(rows), "by_type": {f"{t} {n}": len(v) for (t, n), v in sorted(by.items())}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
