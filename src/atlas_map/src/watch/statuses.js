import { statusGroup } from "../data/format.js";
import { RECORDING } from "./watch.js";

// Each sensor's status on the map, kept current: the bundle's comes from a Nereus snapshot of the RS instruments
// (19 Sep 2026), so every Endurance instrument read "Status unknown" (80 of 203 placed sensors). Nereus's live
// operational status (the Watcher's /v1/watch/live, every RS and Endurance instrument) replaces it, found by the
// sensor's designator or an alias (A-0-A is RS03CCAL-MJ03F-07-A0ABPA301 in Nereus); a sensor Nereus does not know that
// the Watcher found recording (the EarthScope seismic stations) is operating.
export function effectiveStatus(sensor, live, states) {
  const instruments = live?.instruments || {};
  const keys = [sensor.refdes, ...(sensor.aliases || [])].filter(Boolean);
  const nereus = keys.map(k => instruments[k]?.operational).find(Boolean);
  if (nereus) return { status: nereus, statusSource: "Nereus (live)" };
  if (sensor.status === "UNKNOWN" && RECORDING.has(states?.[sensor.id]?.state)) return { status: "OPERATIONAL", statusSource: "Watcher: recording" };
  return null;
}

// Sets them on the bundle's sensors (status, statusGroup, statusSource); true when any changed.
export function applyStatuses(bundle, live, states) {
  let changed = false;
  for (const s of bundle.sensors) {
    s.catalogStatus ??= { status: s.status, statusSource: s.statusSource };
    const next = effectiveStatus({ ...s, status: s.catalogStatus.status }, live, states) ?? s.catalogStatus;
    if (next.status !== s.status) changed = true;
    Object.assign(s, next, { statusGroup: statusGroup(next.status) });
  }
  return changed;
}
