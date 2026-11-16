import { useState } from "react";
import { useWatch } from "./WatchProvider.jsx";
import { WATCH_LABEL } from "./watch.js";
import "./watch.css";

const fmtDay = day => new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const fmtTime = t => new Date(t).toLocaleString("en-US", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" });
// The report's span: the 24 hours to when it ran, or (an older or re-graded report) one UTC day.
export const reportSpan = report => (report.to && !report.to.endsWith("T00:00:00Z") ? `24 h to ${fmtTime(report.to)} UTC` : `${fmtDay(report.day)} UTC`);
const MEANING = {
  no_data: "No sample for 24 hours or more",
  diverted: "High-rate data held back by the Navy: 8 Hz seismic data arriving without the 200 Hz, broadband hydrophones without their files",
  gaps: "Samples in the 24 hours, but a gap longer than normal for it",
};

// The Watcher view's key, under the dock while the owl button is on: what each colour means and how many sensors
// show it, the day the report graded, and when Nereus's live status was read. A colour's row opens the list of its
// sensors (site, since when); a sensor in it opens its card.
export function WatchKey({ bundle, onSensor }) {
  const { report, live, counts, states } = useWatch();
  const [open, setOpen] = useState(null);
  if (!report) return <div className="panel watch-key"><div className="eyebrow">Watcher</div><p className="hint">The daily report is not available just now.</p></div>;
  const site = id => bundle?.siteById?.[bundle?.sensorById?.[id]?.site]?.label;
  const of = k => Object.entries(states).filter(([, s]) => s.state === k)
    .map(([id, s]) => ({ id, name: bundle?.sensorById?.[id]?.name || s.name, site: site(id) || s.site || "", since: s.since, live: s.day === false }))
    // The site is on its own line: a name that starts with it ("Oregon Offshore Cabled Shallow Profiler Mooring CTD") drops it.
    .map(r => ({ ...r, short: r.site && r.name.startsWith(`${r.site} `) ? r.name.slice(r.site.length + 1) : r.name }))
    .sort((a, b) => a.site.localeCompare(b.site) || a.name.localeCompare(b.name));
  return (
    <div className="panel watch-key">
      <div className="eyebrow">Watcher · daily check {reportSpan(report)}</div>
      {["no_data", "diverted", "gaps"].map(k => (
        <div key={k}>
          <button className="row" title={MEANING[k]} aria-expanded={open === k} disabled={!counts[k]}
            onClick={() => setOpen(open === k ? null : k)}>
            <span className={`watch-dot ${k}`} aria-hidden="true" />{WATCH_LABEL[k]}<b className="mono">{counts[k]}</b>
          </button>
          {open === k && (
            <ul className="watch-list" aria-label={`${WATCH_LABEL[k]}: sensors`}>
              {of(k).map(r => (
                <li key={r.id}><button onClick={() => onSensor?.(r.id)}>
                  <span className="nm" title={r.name}>{r.short}</span>
                  <span className="d">{r.site}{r.since && k !== "diverted" ? ` · since ${fmtDay(r.since.slice(0, 10))}` : ""}{r.live ? " · checked live" : ""}</span>
                </button></li>
              ))}
            </ul>
          )}
        </div>
      ))}
      <div className="row muted"><span className="watch-dot ok" aria-hidden="true" />Recording<b className="mono">{counts.recording - counts.gaps - counts.diverted}</b></div>
      <p className="hint">{counts.watched} sensors watched; those recording normally are not highlighted.
        {live?.fetchedAt ? ` Checked live by Nereus: ${fmtTime(live.fetchedAt)} UTC (marked "checked live" where it changed the daily check).` : ""}
        {report.axial200Hz === "Navy Diversion" ? " Axial catalog: 200 Hz data under Navy diversion." : ""}</p>
    </div>
  );
}

export function WatchDot({ id }) {
  const { on, states } = useWatch();
  const st = states[id]?.state;
  if (!on || !["no_data", "diverted", "gaps"].includes(st)) return null;
  return <span className={`watch-dot ${st}`} title={WATCH_LABEL[st]} aria-label={WATCH_LABEL[st]} />;
}
