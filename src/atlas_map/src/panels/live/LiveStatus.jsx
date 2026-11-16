import { status as fetchStatus, waveformHealth } from "../../api/gateway.js";
import { fmtDate, fmtMinutes, fmtUtc, statusLabel } from "../../data/format.js";
import { useLive } from "./useLive.js";

export default function LiveStatus({ sensor, manifest }) {
  const live = useLive(sensor.refdes ? `status:${sensor.refdes}` : null, o => fetchStatus(sensor.refdes, o));
  const earthscope = sensor.refdes ? null : sensor.access.find(a => a.kind === "earthscope");
  const waveform = useLive(earthscope ? `wave-health:${earthscope.network}.${earthscope.station}:${earthscope.channel}` : null,
    o => waveformHealth(`${earthscope.network}.${earthscope.station}`, earthscope.channel, o));
  const snapshot = `${statusLabel(sensor.status)}${sensor.statusSource ? ` · ${sensor.statusSource}` : ""}`;
  if (earthscope) {
    if (waveform.state === "idle" || waveform.state === "loading") return <div className="live-status">Checking recent EarthScope waveform…</div>;
    if (waveform.state === "ok") {
      const d = waveform.data;
      // EarthScope's archive often trails real time by an hour or more; say so rather than imply a live stream.
      const lag = d.recording && d.delayMinutes >= 5 ? ` · EarthScope archive ${fmtMinutes(d.delayMinutes)} behind` : "";
      // A stalled high-rate channel (HHZ) gave way to a current lower-rate one (MHZ): say which, so 8 samples/s is not taken for the full stream.
      const via = d.recording && d.requestedChannel && d.requestedChannel !== d.channel
        ? ` on ${d.channel}${d.rate ? ` (${d.rate} samples/s)` : ""}; no recent ${d.requestedChannel} at EarthScope` : "";
      return <div className="live-status">{d.recording ? `Waveform available${via}${lag}` : (d.message ?? "No recent waveform")} · EarthScope checked live</div>;
    }
    if (waveform.error.kind === "unreachable") return <div className="live-status degraded">EarthScope live check unavailable <button onClick={waveform.retry}>Retry</button></div>;
    return <div className="live-status degraded">EarthScope: {waveform.error.message} <button onClick={waveform.retry}>Retry</button></div>;
  }
  if (!sensor.refdes || live.state === "idle") return <div className="live-status">{snapshot}</div>;
  if (live.state === "loading") return <div className="live-status">{snapshot} · checking live…</div>;
  if (live.state === "ok" && live.data.evidenceMode === "data_age") {
    // Nereus does not track this sensor; the gateway reports how recent its data are instead (ERDDAP's newest
    // reading, else its QA/QC day plot's date). Data age, not an operational status, so no status is claimed.
    const d = live.data, at = new Date(d.latestAt), stale = Date.now() - at > 3 * 864e5;
    const when = `${fmtDate(d.latestAt)}${d.basis === "erddap" ? `, ${at.toUTCString().slice(17, 22)} UTC` : ""}`;
    // Recent ERDDAP readings make it operating (the gateway decides); the data's age and source stay visible.
    if (d.status) return <div className="live-status">{statusLabel(d.status)} · data through {when} · OOI ERDDAP</div>;
    const what = d.basis === "erddap" ? `Data through ${when} · OOI ERDDAP` : `QA/QC plots updated ${when}`;
    return <div className={`live-status${stale ? " degraded" : ""}`}>{what} · not tracked by Nereus</div>;
  }
  if (live.state === "ok") {
    const d = live.data;
    // Nereus's operational status (an operator's call), then its data check in words. "Checked live, data UNMONITORED"
    // read as a live data check for the Central Caldera BOTPT, whose data Nereus does not check (the Watcher, below,
    // says what its data show). Nereus answers live, or falls back to its snapshot; never claim both.
    const who = !d.evidenceMode || d.evidenceMode === "live" ? "per Nereus"
      : d.evidenceMode === "snapshot" ? "from Nereus snapshot" : `from Nereus (${d.evidenceMode})`;
    const code = d.data?.code, at = d.data?.checkedAt ? ` at ${fmtUtc(d.data.checkedAt)}` : "";
    const check = !d.data ? "" : !code || code === "UNMONITORED" ? " · Nereus does not check its data"
      : ` · its data check was ${({ GOOD: "good", OK: "good", BAD: "bad", WARN: "a warning" })[code] ?? code.toLowerCase()}${at}`;
    return <div className="live-status">{statusLabel(d.status ?? "UNKNOWN")}, {who}{check}</div>;
  }
  if (live.error.kind === "unreachable") {
    return <div className="live-status degraded"><span>Live data unavailable. Showing snapshot from {fmtDate(sensor.statusAsOf ?? manifest?.corpusSnapshot)}.</span>
      <button onClick={live.retry}>Retry</button></div>;
  }
  if (live.error.kind === "notfound") {
    return <div className="live-status">{snapshot} · {live.error.source === "Nereus" ? "not tracked live by Nereus" : `${live.error.source}: ${live.error.message}`}</div>;
  }
  return <div className="live-status degraded">{snapshot} · {live.error.source} failed: {live.error.message} <button onClick={live.retry}>Retry</button></div>;
}
