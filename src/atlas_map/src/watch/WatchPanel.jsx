import { useWatch } from "./WatchProvider.jsx";
import { WATCH_LABEL } from "./watch.js";
import "./watch.css";

const fmtDay = day => new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const MEANING = {
  no_data: "No data for a day or more",
  diverted: "8 Hz seismic data arriving without the 200 Hz: the Navy's diversion",
  gaps: "Recording, with a gap longer than normal for it",
};

// The Watcher view's key, under the dock while the owl button is on: what each colour means and how many sensors
// show it, the day the report graded, and when Nereus's live status was read.
export function WatchKey() {
  const { report, live, counts } = useWatch();
  if (!report) return <div className="panel watch-key"><div className="eyebrow">Watcher</div><p className="hint">The daily report is not available just now.</p></div>;
  return (
    <div className="panel watch-key">
      <div className="eyebrow">Watcher · {fmtDay(report.day)} UTC</div>
      {["no_data", "diverted", "gaps"].map(k => (
        <div key={k} className="row" title={MEANING[k]}>
          <span className={`watch-dot ${k}`} aria-hidden="true" />{WATCH_LABEL[k]}<b className="mono">{counts[k]}</b>
        </div>
      ))}
      <div className="row muted"><span className="watch-dot ok" aria-hidden="true" />Recording<b className="mono">{counts.recording - counts.gaps - counts.diverted}</b></div>
      <p className="hint">{counts.watched} sensors watched; those recording normally are not highlighted.
        {live?.fetchedAt ? ` Nereus live status ${live.fetchedAt.slice(11, 16)} UTC.` : ""}
        {report.axial200Hz ? ` Axial catalog: 200 Hz data ${report.axial200Hz.toLowerCase().startsWith("navy") ? "under " : ""}${report.axial200Hz}.` : ""}</p>
    </div>
  );
}

// A sensor's line in the Watcher: its state, since when, and why.
export function WatchLine({ id }) {
  const { report, states } = useWatch();
  const s = states[id];
  if (!report || !s) return null;
  const since = s.since && s.state !== "ok" ? ` since ${fmtDay(s.since.slice(0, 10))}` : "";
  return (
    <section className="watch-line"><h3>Watcher</h3>
      <p><span className={`watch-dot ${s.state}`} aria-hidden="true" />{WATCH_LABEL[s.state] || s.state}{since}
        {s.nereusStatus && s.nereusStatus !== "OPERATIONAL" ? ` · Nereus: ${s.nereusStatus.toLowerCase().replaceAll("_", " ")}` : ""}</p>
      {s.detail && <p className="hint">{s.detail}</p>}
      <p className="hint">{s.day ? `${fmtDay(report.day)}, checked by ${s.source || s.method}` : "Nereus's live status, over the day's report"}
        {s.erddap && s.agree === false ? `; ERDDAP: ${WATCH_LABEL[s.erddap.state] || s.erddap.state}` : ""}.</p>
    </section>
  );
}

export function WatchDot({ id }) {
  const { on, states } = useWatch();
  const st = states[id]?.state;
  if (!on || !["no_data", "diverted", "gaps"].includes(st)) return null;
  return <span className={`watch-dot ${st}`} title={WATCH_LABEL[st]} aria-label={WATCH_LABEL[st]} />;
}
