import { useState } from "react";
import { fmtUtc } from "../../data/format.js";
import FileBrowser from "./FileBrowser.jsx";
import OsuPlots from "./OsuPlots.jsx";
import PlotGallery from "./PlotGallery.jsx";
import ScprSeries from "./ScprSeries.jsx";
import SeriesView from "./SeriesView.jsx";
import WaveformView from "./WaveformView.jsx";

// One primary view, in this order: ERDDAP series, else EarthScope waveform, else the SCPR's hourly CSV, else QA/QC
// plots; then OSU's Axial plots and PI files (a link beside a plot, else the file browser). QA/QC plots are filed under the route's refdes: a seismometer's is its OOI OBS.
export default function LiveData({ sensor }) {
  const by = k => sensor.access.find(a => a.kind === k);
  const erddap = by("erddap"), es = by("earthscope"), scpr = by("scpr_hourly"), qaqc = by("qaqc"), osu = by("osu_axial"),
    pi = sensor.access.filter(a => a.kind === "pi_portal");
  const plotsRef = qaqc?.refdes ?? sensor.refdes;
  // A sensor with a plot links to its PI portal files (the combined folder, which holds the others) rather than browsing
  // each folder: the SCPR's five routes listed only their year folders. One with nothing else keeps the browser; Get
  // this data lists every route.
  const piLink = (erddap || es || scpr || qaqc) && pi.length ? (pi.find(r => /combined/i.test(r.label)) ?? pi[0]) : null;
  // ERDDAP's copy can stop while the instrument records on (the Oregon Offshore current meter's ends 1 Oct 2026, the
  // Shelf one's in March 2024; Nereus has both recording, and their QA/QC plots are redrawn daily): say so, and show the
  // QA/QC plots as the current view.
  const [erddapEnd, setErddapEnd] = useState(null);
  const stale = !!erddapEnd && Date.now() - Date.parse(erddapEnd) > 2 * 864e5;
  return (
    <section className="live-data"><h3>Live data</h3>
      {erddap ? <SeriesView refdes={sensor.refdes} onCoverage={setErddapEnd} /> : es ? <WaveformView route={es} /> : scpr ? <ScprSeries route={scpr} />
        : qaqc ? <PlotGallery refdes={plotsRef} /> : null}
      {erddap && stale && <p className="series-empty">OOI ERDDAP has this sensor's data only to {fmtUtc(erddapEnd)}.
        {qaqc ? " Its recent data are in the RCA QA/QC plots below." : " Its recent data are not on ERDDAP; see Get this data for OOI's other routes."}</p>}
      {(erddap || es) && qaqc && (stale ? <PlotGallery refdes={plotsRef} /> : <Lazy summary="Recent QA/QC plots">{() => <PlotGallery refdes={plotsRef} />}</Lazy>)}
      {osu && <Lazy summary="OSU Axial monitoring plots">{() => <OsuPlots route={osu} />}</Lazy>}
      {piLink ? <p className="pi-link"><a href={piLink.url} target="_blank" rel="noreferrer">Data files on the PI data portal ↗</a></p>
        : pi.map(r => <FileBrowser key={r.endpointId ?? r.url} route={r} />)}
    </section>
  );
}

// A gallery (and its requests) waits until the reader first opens the section; it stays mounted after that.
function Lazy({ summary, children }) {
  const [opened, setOpened] = useState(false);
  return (
    <details onToggle={e => e.currentTarget.open && setOpened(true)}>
      <summary>{summary}</summary>
      {opened && children()}
    </details>
  );
}
