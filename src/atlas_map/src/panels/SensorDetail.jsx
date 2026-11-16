import Glyph from "../ui/Glyph.jsx";
import GetThisData from "./GetThisData.jsx";
import LiveData from "./live/LiveData.jsx";
import { fmtDepth, fmtRange } from "../data/format.js";
import SensorStatus from "../watch/SensorStatus.jsx";

// `backLabel` names where the back control returns (a site, or the unplaced list); it defaults to the sensor's site.
// One order, each kind of information once: what it is; its status (SensorStatus); its data; how to get them; sources.
export default function SensorDetail({ sensor, bundle, onBack, backLabel }) {
  const fam = bundle.familyByKey[sensor.family];
  const hasLive = sensor.access.some(a => ["erddap", "earthscope", "scpr_hourly", "qaqc", "pi_portal"].includes(a.kind));
  return (
    <div className="sensor-detail">
      <button className="back" onClick={onBack}>← {backLabel ?? bundle.siteById[sensor.site]?.label ?? "Back"}</button>
      <h2><Glyph glyph={fam.glyph} color={fam.color} size={13} /> {sensor.name}</h2>
      <div className="meta mono">{sensor.type.replaceAll("_", " ")} · {sensor.depthRange ? fmtRange(...sensor.depthRange) : fmtDepth(sensor.depth)}
        {sensor.manufacturer ? ` · ${sensor.manufacturer}${sensor.model ? " " + sensor.model : ""}` : ""}</div>
      {sensor.lat == null && <div className="meta">No recorded position, so it is not drawn on the map.</div>}
      <h3 className="status-head">Status</h3>
      <SensorStatus sensor={sensor} manifest={bundle.manifest} />
      {hasLive ? <LiveData sensor={sensor} /> :
        <section className="no-feed"><h3>Live data</h3><p>No live feed. {sensor.statusGroup === "planned" ? "This sensor is planned for COSZO. All data streams will be available to download through EarthScope once all systems are operational." : sensor.access.some(a => a.kind === "ucsd_ascpr") ? "Its data are short ROV visits, one file each; see Get this data." : "No public data service is known for this sensor."}</p></section>}
      <GetThisData sensor={sensor} />
      {(sensor.sources.length > 0 || sensor.corrections.length > 0) && (
        <details className="sources"><summary>Sources ({sensor.sources.length}){sensor.corrections.length ? ` · ${sensor.corrections.length} correction${sensor.corrections.length > 1 ? "s" : ""}` : ""}</summary>
          {sensor.sources.map(u => <a key={u} href={u} target="_blank" rel="noreferrer">{u}</a>)}
          {sensor.corrections.map(c => <p key={c} className="correction">Corrected in the atlas: {c}</p>)}
        </details>
      )}
    </div>
  );
}
