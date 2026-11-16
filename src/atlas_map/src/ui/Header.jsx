import logo from "../assets/atlas-logo-dark.png";
import { MinButton, MinTab, useMinimized } from "./Minimize.jsx";
import Search from "./Search.jsx";
import { useWatch } from "../watch/WatchProvider.jsx";
import "./ui.css";

export default function Header({ bundle, onPick }) {
  const located = bundle.sensors.filter(s => s.lat != null);
  // Operating: the sensors the Watcher found recording (normally, with gaps, or diverted), else the catalog's status.
  const { counts, report } = useWatch();
  const operating = counts ? counts.recording : located.filter(s => s.statusGroup === "operating").length;
  const operatingTitle = counts ? `Recording on ${report.day} (UTC), by the Watcher, with Nereus's live status` : "Operating, by the catalog's status";
  const [min, setMin] = useMinimized("header");
  if (min) return <MinTab className="header-toggle" title="Show the title, counts, and search" onClick={() => setMin(false)}>Cascadia Offshore Sensor Atlas</MinTab>;
  return (
    <header className="panel header">
      <div className="panel-head">
        <div className="brand"><img className="logo" src={logo} alt="Atlas" width="44" height="44" /><h1>Cascadia Offshore Sensor Atlas</h1></div>
        <MinButton label="title and search" onClick={() => setMin(true)} />
      </div>
      <p>OOI Regional Cabled Array and COSZO sensors, offshore Oregon.</p>
      <div className="stats">
        <div><b className="mono">{located.length}</b><span>Sensors</span></div>
        <div title={operatingTitle}><b className="mono">{operating}</b><span>Operating</span></div>
        <div><b className="mono">{bundle.sites.length}</b><span>Sites</span></div>
      </div>
      <Search bundle={bundle} onPick={onPick} />
    </header>
  );
}
