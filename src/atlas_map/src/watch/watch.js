import { atlasUrl } from "../data/bundle.js";
import { ATLAS_WORKER } from "../api/gateway.js";

// The Watcher: which sensors stopped recording. The daily report (atlas/watch/latest.json, written each UTC day by the
// coszo-hub.github.io workflow from src/atlas_watch/check.py) grades the day before; Nereus's live status (the Worker's
// /v1/watch/live) is laid over it, so a sensor that stopped since midnight shows now.
//   gaps      recording, with a gap longer than normal for it (yellow)
//   diverted  8 Hz seismic data reaching EarthScope without the 200 Hz: the Navy's diversion (blue)
//   no_data   nothing for a day or more (red)
// ok, unchecked and failed (the check could not be made) are not highlighted.
export const WATCH_LIVE_URL = import.meta.env.PROD ? `${ATLAS_WORKER}/v1/watch/live` : "/api/watch-live";
export const PROBLEM = ["no_data", "diverted", "gaps"];   // worst first
export const RECORDING = new Set(["ok", "gaps", "diverted"]);
export const WATCH_LABEL = { no_data: "Not recording", diverted: "Navy diversion", gaps: "Gaps", ok: "Recording",
  unchecked: "Not checked", failed: "Check failed" };

const getJson = async (url, signal) => {
  const r = await fetch(url, { signal, headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
};
export const loadReport = signal => getJson(atlasUrl("watch/latest.json"), signal);
export const loadLive = signal => getJson(WATCH_LIVE_URL, signal);

const DAY_MIN = 1440;
const minutesAgo = (now, min) => new Date(now - min * 60_000).toISOString();

// One sensor's state now: the report's, unless Nereus's live check, where it checks the sensor, says otherwise. A
// sensor Nereus finds bad for a day or more is red from when it stopped; bad for longer than its normal gap, yellow; good
// again after a red or yellow day that Nereus graded, recording again. Navy diversion, an EarthScope finding, stays.
export function currentState(row, live, now = Date.now()) {
  const nereus = row.refdes && live?.instruments?.[row.refdes];
  const base = { state: row.state, since: row.since, detail: row.detail || null, day: true };
  if (!nereus || !nereus.check || nereus.check === "UNMONITORED" || row.state === "diverted") return base;
  const delay = nereus.delayMin;
  if (nereus.check === "BAD") {
    if (delay == null || delay >= DAY_MIN) {
      const since = delay == null ? row.since : minutesAgo(now, delay).slice(0, 10);
      return { state: "no_data", since: row.state === "no_data" && row.since < since ? row.since : since,
        detail: delay == null ? "Nereus finds no data now" : `Nereus finds no data for ${Math.round(delay / 60)} hours`, day: false };
    }
    if (delay > (row.gap ?? 60)) return { state: "gaps", since: minutesAgo(now, delay).slice(0, 10),
      detail: `Nereus finds it ${Math.round(delay)} minutes behind now`, day: false };
    return base;
  }
  if ((nereus.check === "GOOD" || nereus.check === "WARN") && (row.state === "no_data" || row.state === "gaps") && /^Nereus/.test(row.source || "")) {
    return { state: "ok", since: null, detail: `Recording again (Nereus, ${String(nereus.checkedAt || "").slice(11, 16)} UTC)`, day: false };
  }
  return base;
}

// Every watched sensor's state now, by sensor id.
export function watchStates(report, live, now = Date.now()) {
  const out = {};
  for (const row of report?.sensors || []) out[row.id] = { ...row, ...currentState(row, live, now) };
  return out;
}

// A site's highlight: its worst problem among its sensors, or null when every watched one is recording or unchecked.
export function siteProblem(site, states) {
  const found = new Set(site.sensorIds.map(id => states[id]?.state));
  return PROBLEM.find(p => found.has(p)) || null;
}

export function watchCounts(states) {
  const counts = { recording: 0, no_data: 0, diverted: 0, gaps: 0, watched: 0 };
  for (const s of Object.values(states)) {
    counts.watched++;
    if (RECORDING.has(s.state)) counts.recording++;
    if (s.state in counts) counts[s.state]++;
  }
  return counts;
}
