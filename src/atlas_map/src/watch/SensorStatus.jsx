import LiveStatus from "../panels/live/LiveStatus.jsx";
import { fmtUtc } from "../data/format.js";
import { useWatch } from "./WatchProvider.jsx";
import { reportSpan } from "./WatchPanel.jsx";

// A sensor card's one status: what the Watcher found its data doing over the 24 hours (with Nereus's live status laid
// over it), in a sentence, then what the operators say (Nereus's status, and their open note on it), then where the
// finding comes from. A sensor the Watcher does not grade (planned, campaign, no public data check) shows the live
// per-instrument status line instead.
const fmtDay = iso => new Date(String(iso).length === 10 ? `${iso}T00:00:00Z` : iso)
  .toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const dur = min => (min >= 120 ? `${Math.round(min / 60)} hours` : `${Math.round(min)} minutes`);
const OPERATIONAL = { FAILED: "failed", OFFLINE: "offline", PARTIALLY_FUNCTIONAL: "partially functional", NOT_DEPLOYED: "not deployed" };

export function sentence(s) {
  const last = s.lastData ? fmtUtc(s.lastData) : s.since ? fmtDay(s.since) : null;
  switch (s.state) {
    case "no_data": return ["Not recording", last ? `no data since ${last}.` : "no data in the last 24 hours."];
    case "diverted": return ["Recording", "its high-rate data are held back by the Navy (Navy diversion)."];
    case "gaps": return ["Recording, with gaps", s.longestGapMin ? `the longest ${dur(s.longestGapMin)} (normal for it: up to ${dur(s.gap)}).` : "longer than normal for it."];
    default: return ["Recording normally", s.lastData ? `data through ${fmtUtc(s.lastData)}.` : ""];
  }
}

const DAILY_WORDS = { no_data: "Not recording", diverted: "Navy diversion", gaps: "Recording, with gaps", ok: "Recording normally" };

// How and when the status was found: the daily check (when it ran, over the 24 hours before) or Nereus's live check
// (when Nereus checked), with what the daily check had said.
export function checkedLine(s, report) {
  const t = report.generatedAt || report.to, daily = t ? fmtUtc(t) : reportSpan(report);
  if (s.day !== false) return `Daily check: ${daily} (the 24 h before) · from ${s.source || s.method}`;
  return `Checked live: ${s.liveAt ? fmtUtc(s.liveAt) : "now"} · by Nereus (daily check, ${daily}: ${DAILY_WORDS[s.dailyState] || s.dailyState})`;
}

export default function SensorStatus({ sensor, manifest }) {
  const { report, states } = useWatch();
  const s = states[sensor.id];
  if (!report || !s || s.state === "unchecked" || s.state === "failed") return <LiveStatus sensor={sensor} manifest={manifest} />;
  const [head, rest] = sentence(s);
  const word = OPERATIONAL[s.nereusStatus];
  return (
    <section className="sensor-status">
      <p className="state"><span className={`watch-dot ${s.state}`} aria-hidden="true" /><b>{head}</b>{rest ? `: ${rest}` : ""}</p>
      {s.detail && <p className="hint">{s.detail}.</p>}
      {s.note ? (
        <details className="note">
          <summary>Operators' note, {fmtDay(s.note.startedAt)}: {s.note.title}{word ? ` · Nereus lists it as ${word}` : ""}</summary>
          <p>{s.note.message}</p>
          <p className="hint">From Nereus, the RCA's instrument monitor; quoted as written.</p>
        </details>
      ) : word && <p className="hint">Nereus, the RCA's instrument monitor, lists it as {word}.</p>}
      {s.erddap && s.agree === false && <p className="hint">OOI ERDDAP disagrees: it found it {s.erddap.state.replace("_", " ")}.</p>}
      <p className="hint src">{checkedLine(s, report)}</p>
    </section>
  );
}
