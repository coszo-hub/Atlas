// The Watcher's live layer (GET /v1/watch/live): Nereus's current status for every instrument it tracks, the RS and
// Endurance cabled arrays, from the one query its Helm page makes (Nereus answers only its own pages' queries; this is
// src/atlas_watch/nereus_helm.graphql). The map lays it over the daily report (atlas/watch/latest.json), so a sensor
// that stopped since midnight shows. Cached five minutes; about 475 kB from Nereus, a few kB out.
export const NEREUS_GRAPHQL = "https://nereus.ooirsn.uw.edu/hasura/v1/graphql";
export const NEREUS_HELM_QUERY = "query HelmQuery {\n    instruments(order_by: { designator: asc }) {\n      ...HelmInstrumentFragment\n    }\n    nodes(order_by: { designator: asc }) {\n      ...HelmNodeFragment\n    }\n  }\n  fragment HelmInstrumentFragment on instruments {\n    __typename\n    id\n    designator\n    details\n    ipAddress: ip_address\n    operationalStatusCode: operational_status_code\n    alertsAreEnabled: alerts_are_enabled\n    alertStateCode: alert_state_code\n    alertStateEndsAt: alert_state_ends_at\n    dataCheckIsEnabled: data_check_is_enabled\n    pingCheckIsEnabled: ping_check_is_enabled\n    fileCheckIsEnabled: file_check_is_enabled\n    gfdCheckIsEnabled: gfd_check_is_enabled\n    powerCheckIsEnabled: power_check_is_enabled\n    isPiInstrument: is_pi_instrument\n    emsPortType: ems_port_type\n    emsPortNumber: ems_port_number\n    latestDataStatusConnection: latest_data_status_connection {\n      __typename\n      status: data_status {\n        __typename\n        instrumentId: instrument_id\n        code\n        delay\n        endedAt: ended_at\n        checkedAt: checked_at\n      }\n    }\n    latestFileStatusConnection: latest_file_status_connection {\n      __typename\n      status: file_status {\n        __typename\n        instrumentId: instrument_id\n        code\n        checkedAt: checked_at\n      }\n    }\n    latestPingStatusConnection: latest_ping_status_connection {\n      __typename\n      status: ping_status {\n        __typename\n        instrumentId: instrument_id\n        code\n        checkedAt: checked_at\n      }\n    }\n    latestGfdStatusConnection: latest_gfd_status_connection {\n      __typename\n      status: gfd_status {\n        __typename\n        instrumentId: instrument_id\n        code\n        codeHigh: code_high\n        codeLow: code_low\n        valueHigh: value_high\n        valueLow: value_low\n        checkedAt: checked_at\n      }\n    }\n    latestPowerStatusConnection: latest_power_status_connection {\n      __typename\n      status: power_status {\n        __typename\n        instrumentId: instrument_id\n        powerState: power_state\n        current\n        voltage\n        checkedAt: checked_at\n      }\n    }\n    currentDeploymentConnection: current_deployment_connection {\n      __typename\n      deployment {\n        id\n        assetId: asset_id\n        cruiseName: cruise_name\n        number\n        startedAt: started_at\n        endedAt: ended_at\n        latitude\n        longitude\n        depth\n        waterDepth: water_depth\n        notes\n        asset {\n          id\n          description\n          manufacturer\n          model\n          type\n          uid\n          serialNumber: serial_number\n        }\n      }\n    }\n    latestDeploymentConnection: latest_deployment_connection {\n      __typename\n      deployment {\n        id\n        assetId: asset_id\n        cruiseName: cruise_name\n        number\n        startedAt: started_at\n        endedAt: ended_at\n        latitude\n        longitude\n        depth\n        waterDepth: water_depth\n        notes\n        asset {\n          id\n          description\n          manufacturer\n          model\n          type\n          uid\n          serialNumber: serial_number\n        }\n      }\n    }\n  }\n\n  fragment HelmNodeFragment on nodes {\n    __typename\n    id\n    parentId: parent_id\n    designator\n    description\n    ipAddress: ip_address\n    mooringUid: mooring_uid\n    site: site\n    type\n    subtype\n    operationalStatusCode: operational_status_code\n    alertsAreEnabled: alerts_are_enabled\n    alertStateCode: alert_state_code\n    alertStateEndsAt: alert_state_ends_at\n    pingCheckIsEnabled: ping_check_is_enabled\n    powerCheckIsEnabled: power_check_is_enabled\n    emsPortType: ems_port_type\n    emsPortNumber: ems_port_number\n    latestPingStatusConnection: latest_ping_status_connection {\n      __typename\n      status: ping_status {\n        __typename\n        nodeId: node_id\n        code\n        checkedAt: checked_at\n      }\n    }\n    latestPowerStatusConnection: latest_power_status_connection {\n      __typename\n      status: power_status {\n        __typename\n        nodeId: node_id\n        powerState: power_state\n        current\n        voltage\n        checkedAt: checked_at\n      }\n    }\n    currentDeploymentConnection: current_deployment_connection {\n      __typename\n      deployment {\n        id\n        assetId: asset_id\n        cruiseName: cruise_name\n        number\n        startedAt: started_at\n        endedAt: ended_at\n        latitude\n        longitude\n        depth\n        waterDepth: water_depth\n        notes\n        asset {\n          id\n          description\n          manufacturer\n          model\n          type\n          uid\n          serialNumber: serial_number\n        }\n      }\n    }\n    latestDeploymentConnection: latest_deployment_connection {\n      __typename\n      deployment {\n        id\n        assetId: asset_id\n        cruiseName: cruise_name\n        number\n        startedAt: started_at\n        endedAt: ended_at\n        latitude\n        longitude\n        depth\n        waterDepth: water_depth\n        notes\n        asset {\n          id\n          description\n          manufacturer\n          model\n          type\n          uid\n          serialNumber: serial_number\n        }\n      }\n    }\n  }\n";
const LIVE_SECONDS = 300;

// Each instrument's operational status, its data check (GOOD, BAD, WARN, UNMONITORED; else its file check, for those
// Nereus checks only by files), minutes behind, and when Nereus checked.
export function nereusSummary(data) {
  const out = {};
  for (const row of data?.instruments || []) {
    if (!row?.designator) continue;
    const status = (kind) => row[`latest${kind}StatusConnection`]?.status || null;
    const data = row.dataCheckIsEnabled ? status("Data") : null;
    const file = row.fileCheckIsEnabled ? status("File") : null;
    const check = data && data.code !== "UNMONITORED" ? { ...data, kind: "data" } : file && file.code !== "UNMONITORED" ? { ...file, kind: "file" } : data || file;
    out[row.designator] = { operational: row.operationalStatusCode || null, check: check?.code || null, kind: check?.kind || null,
      delayMin: check?.delay ?? null, checkedAt: check?.checkedAt || null };
  }
  return out;
}

// Nereus's live summary, from the Worker's cache when it is under five minutes old.
async function nereusLive(ctx) {
  const cache = typeof caches !== "undefined" ? caches.default : null;
  const key = new Request("https://rca-atlas.cache/v1/watch/live");
  const cached = cache && await cache.match(key);
  if (cached) return cached.json();
  const upstream = await fetch(NEREUS_GRAPHQL, {
    method: "POST", headers: { "content-type": "application/json", "user-agent": "RCA-Atlas-Watcher/1.0" },
    body: JSON.stringify({ operationName: "HelmQuery", variables: {}, query: NEREUS_HELM_QUERY }), signal: AbortSignal.timeout(20_000),
  });
  const result = upstream.ok ? await upstream.json() : null;
  if (!result?.data) throw new Error(`Nereus ${upstream.status}`);
  const live = { source: "Nereus", fetchedAt: new Date().toISOString(), instruments: nereusSummary(result.data) };
  if (cache) {
    const put = cache.put(key, new Response(JSON.stringify(live), { headers: { "content-type": "application/json", "cache-control": `public, max-age=${LIVE_SECONDS}` } }));
    if (ctx?.waitUntil) ctx.waitUntil(put); else await put;
  }
  return live;
}

export async function watchLive(cors, ctx) {
  try {
    const live = await nereusLive(ctx);
    return new Response(JSON.stringify(live), { status: 200, headers: { ...cors, "content-type": "application/json", "cache-control": `public, max-age=${LIVE_SECONDS}` } });
  } catch {
    return new Response(JSON.stringify({ error: { source: "Nereus", message: "Nereus is unreachable just now" } }),
      { status: 503, headers: { ...cors, "content-type": "application/json", "cache-control": "no-store" } });
  }
}

// Ask Atlas: "which sensors stopped recording?", "are any instruments down?", "what is under Navy diversion?". The
// daily report (the map's atlas/watch/latest.json) with Nereus's live status laid over it, as the map's Watcher view
// shows it (src/atlas_map/src/watch/watch.js, currentState).
export const WATCH_REPORT_URL = "https://coszo.org/atlas/atlas/watch/latest.json";
const PROBLEM_WORDS = /\b(?:stopped|stop recording|not recording|no data|down|offline|not working|failed|failing|broken|gaps?|missing data|outages?|diver(?:ted|sion))\b/i;
export function isWatchQuestion(question) {
  const q = String(question || "");
  return /\bnavy diversion\b|\bwatcher\b/i.test(q)
    || (/\b(?:which|what|list|any|how many|are there)\b/i.test(q) && /\b(?:sensors?|instruments?|stations?|seismometers?|hydrophones?)\b/i.test(q) && PROBLEM_WORDS.test(q));
}

const DAY_MIN = 1440;
// As the map's (src/atlas_map/src/watch/watch.js): when a sensor stopped is the report's last data time, Nereus's delay
// only without one (it read 148 days for hydrophones good until the day before), never before the day the report saw
// it recording.
export function currentState(row, live, now = Date.now(), from = null) {
  const nereus = row.refdes && live?.instruments?.[row.refdes];
  const base = { state: row.state, since: row.since, detail: row.detail || null, live: false };
  if (!nereus || !nereus.check || nereus.check === "UNMONITORED" || row.state === "diverted") return base;
  if (nereus.check === "BAD") {
    let stopped = row.lastData ? Date.parse(row.lastData) : nereus.delayMin != null ? now - nereus.delayMin * 60_000 : null;
    if (stopped != null && from && row.state !== "no_data") stopped = Math.max(stopped, Date.parse(from.length === 10 ? `${from}T00:00:00Z` : from));
    const minutes = stopped == null ? null : (now - stopped) / 60_000;
    const at = stopped == null ? "" : new Date(stopped).toISOString().slice(0, 16).replace("T", " ");
    if (minutes == null || minutes >= DAY_MIN) {
      return { state: "no_data", since: row.state === "no_data" ? row.since : at.slice(0, 10) || row.since,
        detail: at ? `Nereus finds no data now; the last was ${at} UTC` : "Nereus finds no data now", live: true };
    }
    if (minutes > (row.gap ?? 60)) return { state: "gaps", since: at.slice(0, 10), detail: `Nereus finds no data since ${at} UTC`, live: true };
    return base;
  }
  if ((nereus.check === "GOOD" || nereus.check === "WARN") && (row.state === "no_data" || row.state === "gaps") && /^Nereus/.test(row.source || "")
      && row.agree !== false) {   // a state ERDDAP's independent check set (it disagreed with Nereus) is not Nereus's to clear
    return { state: "ok", since: null, detail: "recording again by Nereus's live check", live: true };
  }
  return base;
}

// The evidence record: the day, the counts, and every sensor not recording, under diversion, or with gaps.
export function watchHit(report, live, now = Date.now()) {
  const rows = (report?.sensors || []).map((row) => ({ ...row, ...currentState(row, live, now, report.from || report.day) }));
  const span = report.to && !report.to.endsWith("T00:00:00Z") ? `the 24 hours to ${report.to.slice(0, 16).replace("T", " ")} UTC` : `${report.day} (UTC)`;
  const of = (state) => rows.filter((r) => r.state === state);
  const id = (r) => r.refdes || r.id.replace(/^EARTHSCOPE-OO-/, "OO.");
  const words = (st) => (st ? st.toLowerCase().replaceAll("_", " ") : "");
  const down = of("no_data"), diverted = of("diverted"), gaps = of("gaps"), unchecked = of("unchecked").length + of("failed").length;
  const recording = rows.length - down.length - unchecked;
  const lines = [
    `Watcher report for ${span}: each watched sensor graded from Nereus's hourly data checks, OOI ERDDAP, EarthScope, OOI's raw data server and the PI data portal${live?.fetchedAt ? `, with Nereus's live status at ${live.fetchedAt.slice(0, 16).replace("T", " ")} UTC laid over it` : ""}.`,
    `${rows.length} sensors watched: ${recording} recording (${recording - gaps.length - diverted.length} normally, ${gaps.length} with gaps longer than normal, ${diverted.length} under the Navy's diversion of their high-rate data), ${down.length} not recording, ${unchecked} not checked (no public data check). Temporary, campaign, planned and not-deployed sensors are not watched.`,
    down.length ? `Not recording (no sample for 24 hours or more):\n${down.map((r) => `- ${r.name} (${id(r)}), since ${String(r.since || "").slice(0, 10)}${r.nereusStatus && r.nereusStatus !== "OPERATIONAL" ? `; Nereus lists it as ${words(r.nereusStatus)}` : ""}${r.live ? `; ${r.detail}` : ""}`).join("\n")}` : "No watched sensor is without data.",
    diverted.length ? `Navy diversion (the high-rate data held back: a seismometer's or low-frequency hydrophone's 8 Hz data reaching EarthScope without its 200 Hz; a broadband hydrophone without its files on the raw data server since they stopped together): ${diverted.map((r) => `${r.name} (${id(r)})`).join("; ")}.` : "",
    gaps.length ? `Recording with gaps (samples in the 24 hours, but a gap longer than normal):\n${gaps.map((r) => `- ${r.name} (${id(r)})${r.detail ? `: ${r.detail}` : r.longestGapMin ? `: a ${r.longestGapMin}-minute gap` : ""}`).join("\n")}` : "",
    // The report keeps one of two fixed values for the page's line (check.py, axial_200hz), never its text.
    report.axial200Hz === "Navy Diversion" ? "The Axial Seamount earthquake catalog page lists its 200 Hz waveform data as under Navy diversion."
      : report.axial200Hz === "No diversion stated" ? "The Axial Seamount earthquake catalog page does not list its 200 Hz waveform data as under Navy diversion." : "",
  ].filter(Boolean);
  return { chunk_id: `WATCHER-${report.day}`, collection_id: "watcher", title: `Watcher report: sensors not recording (${report.day})`,
    text: lines.join("\n"), citations: [{ source_id: "WATCHER", title: "RCA Atlas Watcher daily report", url: WATCH_REPORT_URL }] };
}

export async function watchRecords(ctx) {
  try {
    const report = await fetch(WATCH_REPORT_URL, { signal: AbortSignal.timeout(15_000) }).then((r) => (r.ok ? r.json() : null));
    if (!report?.sensors) return [];
    const live = await nereusLive(ctx).catch(() => null);
    return [watchHit(report, live)];
  } catch (error) {
    console.error("watcher report failed", error instanceof Error ? error.message : "unknown");
    return [];
  }
}
