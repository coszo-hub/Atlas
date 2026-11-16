import { atlasUrl } from "../data/bundle.js";
import { ATLAS_WORKER } from "../api/gateway.js";

// The Watcher: which sensors stopped recording. The daily report (atlas/watch/latest.json, written each UTC day by the
// coszo-hub.github.io workflow from src/atlas_watch/check.py) grades the day before; Nereus's live status (the Worker's
// /v1/watch/live) is laid over it, so a sensor that stopped since midnight shows now.
//   gaps      recording, with a gap longer than normal for it (yellow)
//   diverted  the Navy's diversion of the high-rate data: 8 Hz seismic data reaching EarthScope without the 200 Hz, and
//             broadband hydrophones without their files when it is so (blue)
//   no_data   no sample for 24 hours or more (red)
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

// One sensor's state now: the report's, unless Nereus's live check, where it checks the sensor, says otherwise. A
// sensor Nereus finds bad for a day or more is red from when it stopped; bad for longer than its normal gap, yellow; good
// again after a red or yellow day that Nereus graded, recording again. Navy diversion, an EarthScope finding, stays.
// When it stopped is the report's last data time: Nereus's "delay" is not always the time since the last data (the
// broadband hydrophones, good until 11:00 UTC on 15 Nov 2026, read 148 days), so it is used only without one, and a
// sensor the report saw recording on its day did not stop before that day.
export function currentState(row, live, now = Date.now(), from = null) {
  const nereus = row.refdes && live?.instruments?.[row.refdes];
  const base = { state: row.state, since: row.since, detail: row.detail || null, day: true };
  if (!nereus || !nereus.check || nereus.check === "UNMONITORED" || row.state === "diverted") return base;
  if (nereus.check === "BAD") {
    let stopped = row.lastData ? Date.parse(row.lastData) : nereus.delayMin != null ? now - nereus.delayMin * 60_000 : null;
    // from: the report's window start (an older report names only its day)
    if (stopped != null && from && row.state !== "no_data") stopped = Math.max(stopped, Date.parse(from.length === 10 ? `${from}T00:00:00Z` : from));
    const minutes = stopped == null ? null : (now - stopped) / 60_000;
    const at = stopped == null ? "" : new Date(stopped).toISOString().slice(0, 16).replace("T", " ");
    if (minutes == null || minutes >= DAY_MIN) {
      return { state: "no_data", since: row.state === "no_data" ? row.since : at.slice(0, 10) || row.since,
        detail: at ? `Nereus finds no data now; the last was ${at} UTC` : "Nereus finds no data now", day: false };
    }
    if (minutes > (row.gap ?? 60)) return { state: "gaps", since: at.slice(0, 10), detail: `Nereus finds no data since ${at} UTC`, day: false };
    return base;
  }
  if ((nereus.check === "GOOD" || nereus.check === "WARN") && (row.state === "no_data" || row.state === "gaps") && /^Nereus/.test(row.source || "")
      && row.agree !== false) {   // a state ERDDAP's independent check set (it disagreed with Nereus) is not Nereus's to clear
    return { state: "ok", since: null, detail: `Recording again (Nereus, ${String(nereus.checkedAt || "").slice(11, 16)} UTC)`, day: false };
  }
  return base;
}

// Every watched sensor's state now, by sensor id.
export function watchStates(report, live, now = Date.now()) {
  const out = {};
  for (const row of report?.sensors || []) out[row.id] = { ...row, ...currentState(row, live, now, report.from || report.day) };
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
