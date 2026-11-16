"""Per-sensor data-access routes. External coverage lists are cached by explicit refresh steps."""
from __future__ import annotations

import csv
import io
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ERDDAP = "https://erddap.dataexplorer.oceanobservatories.org/erddap"
QAQC = "https://ec2.qaqc.ooi-rca.net"
OOI_EXPLORER = "https://dataexplorer.oceanobservatories.org"
# Corpus channels.jsonl gives each OO station's vertical channel; the EarthScope inventory (cached by
# --refresh-external) fills in any it lacks: broadband stations publish HHZ, the short-period ones (AXAS1, AXEC1, HYS11, ...) EHZ.
DEFAULT_VERTICAL_CHANNEL = "HHZ"
VERTICAL_PREFERENCE = ("HHZ", "EHZ", "BHZ", "SHZ")
FDSN_STATION = "https://service.earthscope.org/fdsnws/station/1/query"
# An OOI low-frequency hydrophone is archived at EarthScope as the HDH channel of the seismic station on its node.
HYDROPHONE_MATCH_KM = 2.0
# The OOI seismometer (OBS) at each OO station, whose QA/QC plots are filed under its reference designator. Paired by
# position: each one's latest deployment in OOI asset-management (deployment/{site}_Deploy.csv) lies within 25 m of
# the station's EarthScope coordinates, most at 0 m, and no other station is within 340 m.
OBS_REFDES = {
    "HYSB1": "RS01SLBS-MJ01A-05-OBSBBA102", "HYS14": "RS01SUM1-LJ01B-05-OBSBBA101",
    "HYS13": "RS01SUM1-LJ01B-06-OBSSPA103", "HYS12": "RS01SUM1-LJ01B-07-OBSSPA102",
    "HYS11": "RS01SUM1-LJ01B-08-OBSSPA101", "AXAS2": "RS03ASHS-MJ03B-05-OBSSPA302",
    "AXAS1": "RS03ASHS-MJ03B-06-OBSSPA301", "AXBA1": "RS03AXBS-MJ03A-05-OBSBBA303",
    "AXCC1": "RS03CCAL-MJ03F-06-OBSBBA301", "AXEC1": "RS03ECAL-MJ03E-05-OBSSPA303",
    "AXEC3": "RS03ECAL-MJ03E-08-OBSSPA304", "AXEC2": "RS03ECAL-MJ03E-09-OBSBBA302",
    "AXID1": "RS03INT2-MJ03D-05-OBSSPA305",
}
ALLOWED_HOSTS = {
    "erddap.dataexplorer.oceanobservatories.org", "dataexplorer.oceanobservatories.org",
    "oceanobservatories.org", "ooinet.oceanobservatories.org", "ec2.qaqc.ooi-rca.net",
    "piweb.ooirsn.uw.edu", "service.earthscope.org", "ds.iris.edu", "www.earthscope.org",
    "interactiveoceans.washington.edu", "axial.ceoas.oregonstate.edu", "coszo.org", "www.coszo.org", "github.com", "doi.org",
    "library.ucsd.edu",
}
# The cabled SCPR's hourly means (both gauges: raw, drift-corrected, and seafloor uplift), which the Axial-Seamount
# self-calibrating-pressure repository regenerates every day. The map reads the CSV from GitHub when the panel opens,
# so the chart follows the daily update without a bundle rebuild.
SCPR_REFDES = "RS03CCAL-MJ03F-09-SCPRAA301"
SCPR_HOURLY_PATH = "Axial-Seamount/self-calibrating-pressure/main/SCPR-data-collection/timeseries/scpr_pressure_hourly.csv"
SCPR_HOURLY = {"kind": "scpr_hourly", "label": "SCPR hourly pressure and uplift (GitHub)",
               "url": "https://github.com/" + SCPR_HOURLY_PATH.replace("/main/", "/blob/main/", 1),
               "csvUrl": "https://raw.githubusercontent.com/" + SCPR_HOURLY_PATH,
               "how": "Hourly means of both gauges since July 2018: raw and drift-corrected pressure (Pa) and estimated "
                      "seafloor uplift (m), as CSV, regenerated daily. Lines starting with # describe the columns."}

# The cabled absolute pressure gauges and point current meters (VEL3D-B) at Slope Base, Southern Hydrate Ridge and Axial
# Base are on EarthScope under their node's seismic station: pressure and housing temperature at location 10, currents
# and water temperature at location 20 (coszo.org/absolute-seafloor-pressure.html, coszo.org/current-meter.html).
# EarthScope's 1 Hz samples are the instrument's own, where ERDDAP has one-minute means, so it is the first route.
EARTHSCOPE_PRODUCTS = {
    "RS01SLBS-MJ01A-06-PRESTA101": ("HYSB1", "10", "pressure"),
    "RS01SUM1-LJ01B-09-PRESTB102": ("HYS14", "10", "pressure"),
    "RS03AXBS-MJ03A-06-PRESTA301": ("AXBA1", "10", "pressure"),
    "RS01SLBS-MJ01A-12-VEL3DB101": ("HYSB1", "20", "currents"),
    "RS01SUM1-LJ01B-12-VEL3DB104": ("HYS14", "20", "currents"),
    "RS03AXBS-MJ03A-12-VEL3DB301": ("AXBA1", "20", "currents"),
    # The Oregon Shelf benthic package's Nortek Vector (VEL3D-C) is at EarthScope under COSZO's shelf station, location
    # 20 (8 Hz east, north and up, MOU/MOV/MOW): its deployments since September 2014, with data for parts of them, where
    # ERDDAP's copy ends in March 2024.
    "CE02SHBP-LJ01D-07-VEL3DC108": ("CZSHF", "20", "currents_c"),
    # The Oregon Offshore benthic package's (VEL3D-C) is under COSZO's offshore station, location 21, from August 2014;
    # ERDDAP's copy ends on 1 Oct 2026.
    "CE04OSBP-LJ01C-07-VEL3DC107": ("CZOFF", "21", "currents_c"),
}
EARTHSCOPE_PRODUCT_CHANNELS = {"pressure": "UDO,LDO,UK1,LK1", "currents": "LOE,LON,LOZ,LKO", "currents_c": "MOU,MOV,MOW,LKO"}
EARTHSCOPE_PRODUCT_PAGES = {"pressure": "https://coszo.org/absolute-seafloor-pressure.html",
                            "currents": "https://coszo.org/current-meter.html", "currents_c": "https://coszo.org/current-meter.html"}


def earthscope_product(refdes: str) -> dict | None:
    """The EarthScope route of a cabled pressure gauge or current meter, or None."""
    if refdes not in EARTHSCOPE_PRODUCTS:
        return None
    sta, loc, product = EARTHSCOPE_PRODUCTS[refdes]
    cha = EARTHSCOPE_PRODUCT_CHANNELS[product]
    what = ("absolute pressure (Pa) and housing temperature" if product == "pressure"
            else "east, north and up current velocity (m/s, 8 samples a second) and water temperature" if product == "currents_c"
            else "east, north and up current velocity (m/s) and water temperature")
    return {"kind": "earthscope", "label": f"EarthScope FDSN ({'absolute pressure' if product == 'pressure' else 'currents'})",
            "network": "OO", "station": sta, "location": loc, "channel": cha, "product": product,
            "channelSource": EARTHSCOPE_PRODUCT_PAGES[product],
            "url": f"https://service.earthscope.org/fdsnws/station/1/query?net=OO&sta={sta}&loc={loc}&cha={cha}&level=channel&format=text",
            "how": f"Public {what} as MiniSEED, every sample, from station OO.{sta} location {loc}; no login."}


def erddap_dataset_id(refdes: str) -> str:
    return "ooi-" + refdes.lower()


def earthscope_station(record: dict) -> tuple[str, str] | None:
    m = re.fullmatch(r"EARTHSCOPE-([A-Z0-9]+)-([A-Z0-9]+)", record["id"])
    return (m.group(1), m.group(2)) if m else None


# COSZO's planned cabled sensors publish nothing yet; their stations (OO.CZSHF, CZOSH, CZMID, CZOFF) are registered at
# EarthScope, where every data stream will be.
PLANNED_HOW = "All data streams will be available to download through EarthScope once all systems are operational."


def planned_route(record: dict) -> dict:
    m = re.fullmatch(r"COSZO-([A-Z0-9]+)-([A-Z0-9]+)-.+", record["id"])
    url = (f"{FDSN_STATION}?net={m.group(1)}&sta={m.group(2)}&level=channel&format=text" if m
           else "https://coszo.org/coszo-instruments.html")
    return {"kind": "planned", "label": "EarthScope (once operational)" + (f": station {m.group(1)}.{m.group(2)}" if m else ""),
            "url": url, "how": PLANNED_HOW}


# The bottom pressure recorder sites O1-O6 are the benchmarks of Cook et al. (2023, JGR Solid Earth,
# doi:10.1029/2023JB026413): an ROV set an Absolute Self-Calibrating Pressure Recorder on each for a few hours a
# survey (2014-2017). Their calibrated absolute sea pressure is in the UC San Diego Library, one CSV a visit; each file's
# station and times were read from the file (its pressure matches the station's depth).
ASCPR_DATASET = "https://library.ucsd.edu/dc/object/bb6529640g"
ASCPR_DOI = "https://doi.org/10.6075/J0F18ZXJ"
ASCPR_VISITS = {   # station -> (component, first and last sample, UTC)
    "O1": [(5, "2014-10-01T22:43:55Z", "2014-10-02T00:33:39Z"), (6, "2014-10-02T06:15:30Z", "2014-10-02T08:06:38Z"),
           (7, "2014-10-03T21:25:31Z", "2014-10-04T03:28:48Z"), (15, "2015-10-21T05:05:30Z", "2015-10-21T07:08:14Z"),
           (23, "2016-06-04T15:57:15Z", "2016-06-04T18:22:44Z"), (42, "2017-09-06T10:58:00Z", "2017-09-06T12:56:44Z")],
    "O2": [(10, "2014-10-02T19:09:00Z", "2014-10-02T20:58:54Z"), (11, "2014-10-03T01:21:06Z", "2014-10-03T03:17:09Z"),
           (12, "2014-10-03T09:31:35Z", "2014-10-03T11:20:58Z"), (18, "2015-10-19T23:56:00Z", "2015-10-20T01:46:04Z"),
           (19, "2015-10-20T06:50:50Z", "2015-10-20T08:40:54Z"), (26, "2016-06-05T21:44:45Z", "2016-06-05T23:30:13Z"),
           (45, "2017-09-05T20:47:30Z", "2017-09-05T22:39:24Z")],
    "O2B": [(20, "2015-10-20T04:10:30Z", "2015-10-20T06:00:14Z"), (27, "2016-06-05T19:11:35Z", "2016-06-05T21:32:58Z")],
    "O3": [(30, "2016-06-06T05:05:35Z", "2016-06-06T07:19:59Z"), (48, "2017-09-05T05:46:50Z", "2017-09-05T07:55:24Z")],
    "O4": [(33, "2016-06-08T08:05:45Z", "2016-06-08T09:52:04Z"), (51, "2017-09-04T17:35:50Z", "2017-09-04T19:42:23Z")],
    "O5": [(36, "2016-06-08T01:58:30Z", "2016-06-08T03:56:14Z"), (54, "2017-09-02T23:50:30Z", "2017-09-03T02:19:19Z"),
           (55, "2017-09-07T02:33:00Z", "2017-09-07T05:12:04Z")],
    "O6": [(39, "2016-06-07T18:30:50Z", "2016-06-07T20:41:58Z"), (58, "2017-09-02T15:55:45Z", "2017-09-02T17:40:59Z"),
           (59, "2017-09-07T12:27:30Z", "2017-09-07T14:02:59Z")],
}


def ascpr_route(record: dict) -> dict | None:
    m = re.fullmatch(r"COSZO-BPR-(O\w+)", record["id"])
    visits = ASCPR_VISITS.get(m.group(1)) if m else None
    if not visits:
        return None
    days = ", ".join(dict.fromkeys(v[1][:10] for v in visits))
    return {"kind": "ucsd_ascpr", "label": "UC San Diego Library: calibrated absolute seafloor pressure (Cook et al., 2023)",
            "url": ASCPR_DATASET, "doi": ASCPR_DOI, "station": m.group(1),
            "files": [{"url": f"{ASCPR_DATASET}/_{c}_1.csv/download", "start": a, "end": b} for c, a, b in visits],
            "how": f"Calibrated absolute seafloor pressure (kPa, two gauges) from ROV visits of a few hours on {days}; "
                   "one CSV a visit, no login. Ocean tides are not removed."}


PI_HOST = "piweb.ooirsn.uw.edu"
DOCUMENTATION_HOW = "No public data feed is known yet; this page documents the sensor."
PI_DIRECTORY_HOW = "Public PI data directory; browse by date."


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).hostname or ""


def _allowed(url: str) -> bool:
    return _host(url) in ALLOWED_HOSTS


def load_external(runtime: Path) -> dict:
    out = {"erddap": set(), "qaqc": set(), "earthscope": {}, "warnings": []}
    for key, name, field in (("erddap", "erddap_datasets.json", "datasetIds"), ("qaqc", "qaqc_refdes.json", "refdes")):
        path = runtime / name
        if path.exists():
            out[key] = set(json.loads(path.read_text())[field])
        else:
            out["warnings"].append(f"{name} missing; run build_atlas_bundle.py --refresh-external")
    path = runtime / "earthscope_channels.json"
    if path.exists():
        out["earthscope"] = json.loads(path.read_text())["stations"]
    else:
        out["warnings"].append("earthscope_channels.json missing; run build_atlas_bundle.py --refresh-external")
    return out


# The RCA's own sites (RS...) and the Coastal Endurance benthic packages it powers (CE04OSBP, CE02SHBP), whose
# instruments the inventory takes from the official OOI site inventory.
CABLED_PREFIXES = ("RS", "CE04OSBP", "CE02SHBP")


def refresh_erddap(runtime: Path, urlopen=urllib.request.urlopen) -> int:
    pattern = "|".join(p.lower() for p in CABLED_PREFIXES)
    url = f"{ERDDAP}/tabledap/allDatasets.csv?datasetID&datasetID=~%22ooi-({pattern}).*%22"
    with urlopen(url, timeout=60) as resp:
        rows = list(csv.reader(io.StringIO(resp.read().decode("utf-8"))))
    ids = sorted({r[0] for r in rows[2:] if r and r[0].startswith(tuple(f"ooi-{p.lower()}" for p in CABLED_PREFIXES))})
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "erddap_datasets.json").write_text(json.dumps(
        {"retrievedAt": datetime.now(timezone.utc).isoformat(), "source": url, "datasetIds": ids}, indent=1))
    return len(ids)


def refresh_earthscope(runtime: Path, network: str = "OO", urlopen=urllib.request.urlopen) -> int:
    """The network's open channels (active now), per station, with the station position."""
    url = f"{FDSN_STATION}?net={network}&level=channel&format=text&endafter={datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%S}"
    with urlopen(url, timeout=60) as resp:
        lines = resp.read().decode("utf-8").splitlines()
    stations: dict[str, dict] = {}
    for line in lines[1:]:
        p = line.split("|")
        if len(p) < 6:
            continue
        st = stations.setdefault(p[1], {"lat": float(p[4]), "lon": float(p[5]), "channels": []})
        if p[3] not in st["channels"]:
            st["channels"].append(p[3])
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "earthscope_channels.json").write_text(json.dumps(
        {"retrievedAt": datetime.now(timezone.utc).isoformat(), "source": url, "network": network, "stations": stations}, indent=1))
    return len(stations)


def inventory_vertical(station: dict | None) -> str | None:
    return next((c for c in VERTICAL_PREFERENCE if station and c in station["channels"]), None)


def hydrophone_station(record: dict, inventory: dict) -> tuple[str, float] | None:
    """The station publishing this OOI low-frequency hydrophone as HDH: the nearest one within HYDROPHONE_MATCH_KM.
    OOI (RS...) sensors only: COSZO's planned hydrophones have stations registered but publish nothing yet."""
    refdes = record.get("refdes") or ""
    if not refdes.startswith("RS") or "HYDLF" not in refdes or record.get("lat") is None:
        return None
    best = None
    for name, st in inventory.items():
        if "HDH" not in st["channels"]:
            continue
        d = math.hypot((st["lat"] - record["lat"]) * 111.2, (st["lon"] - record["lon"]) * 111.32 * math.cos(math.radians(record["lat"])))
        if d <= HYDROPHONE_MATCH_KM and (best is None or d < best[1]):
            best = (name, d)
    return best


def refresh_qaqc(runtime: Path, index_paths: list[str]) -> int:
    refdes = sorted({p.rsplit("/", 1)[-1].split("_", 1)[0] for p in index_paths if p.startswith(CABLED_PREFIXES)})
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "qaqc_refdes.json").write_text(json.dumps(
        {"retrievedAt": datetime.now(timezone.utc).isoformat(), "source": f"{QAQC}/QAQC_plots/index.json",
         "refdes": refdes}, indent=1))
    return len(refdes)


def build_access(record: dict, external: dict, pi_endpoints: dict[str, list[dict]],
                 vertical_channels: dict[str, str]) -> list[dict]:
    if record.get("status") == "PLANNED":
        return [planned_route(record)]
    routes: list[dict] = []
    refdes = record.get("refdes")
    if refdes:
        ds = erddap_dataset_id(refdes)
        if ds in external["erddap"]:
            routes.append({"kind": "erddap", "label": "OOI ERDDAP (public, no login)", "datasetId": ds,
                           "url": f"{ERDDAP}/tabledap/{ds}.html",
                           "how": "Choose variables and a time range, then download CSV or NetCDF."})
        if refdes in external["qaqc"]:
            routes.append({"kind": "qaqc", "label": "RCA QA/QC plots", "refdes": refdes,
                           "url": f"{QAQC}/", "how": "Pre-rendered charts of recent data, updated by the RCA team."})
        if (product := earthscope_product(refdes)):
            routes.insert(0, product)
        if refdes in external.get("osu_axial", {}):
            routes.append(external["osu_axial"][refdes])
        if refdes == SCPR_REFDES:
            routes.append(dict(SCPR_HOURLY))
        routes.append({"kind": "ooi_explorer", "label": "OOI Data Explorer", "refdes": refdes,
                       "url": f"{OOI_EXPLORER}/#ooi/search/{urllib.parse.quote(refdes)}",
                       "how": "Browse and request OOI data products for this instrument."})
    inventory = external.get("earthscope", {})
    station = earthscope_station(record)
    if station:
        net, sta = station
        channel, source = vertical_channels.get(f"{net}.{sta}"), "station metadata"
        if not channel:
            channel, source = inventory_vertical(inventory.get(sta)), "EarthScope inventory"
        station_url = f"https://service.earthscope.org/fdsnws/station/1/query?net={net}&sta={sta}&level=channel&format=text"
        if not channel and inventory and sta not in inventory:
            # The inventory lists only channels open now. A station absent from it has closed (AXCC2's tilt and
            # acceleration channels ended in 2021), so it gets its archive's metadata, not a live waveform to probe.
            routes.append({"kind": "documentation", "label": "EarthScope station metadata (station closed)", "url": station_url,
                           "how": "EarthScope lists no open channels for this station; the metadata gives each channel's dates."})
        else:
            routes.append({"kind": "earthscope", "label": "EarthScope FDSN", "network": net, "station": sta,
                           "channel": channel or DEFAULT_VERTICAL_CHANNEL,
                           "channelSource": source if channel else "default",
                           "url": station_url,
                           "how": "Public seismic waveforms (MiniSEED) and station metadata; no login."})
        obs = OBS_REFDES.get(sta) if net == "OO" else None
        if obs in external["qaqc"]:
            routes.append({"kind": "qaqc", "label": "RCA QA/QC plots", "refdes": obs,
                           "url": f"{QAQC}/", "how": f"Pre-rendered charts of recent ground motion, filed as {obs}."})
    hyd = hydrophone_station(record, inventory)
    if hyd:
        sta, km = hyd
        routes.append({"kind": "earthscope", "label": "EarthScope FDSN (hydrophone)", "network": "OO", "station": sta,
                       "channel": "HDH", "channelSource": f"co-located station, {km:.1f} km",
                       "url": f"https://service.earthscope.org/fdsnws/station/1/query?net=OO&sta={sta}&cha=HDH&level=channel&format=text",
                       "how": "Public hydrophone waveforms (MiniSEED, 200 samples/s) from the seismic station on this node; no login."})
    for ep in pi_endpoints.get(record["instrumentId"], []):
        routes.append({"kind": "pi_portal", "label": f"PI data portal: {ep['label']}", "instrumentKey": ep["instrument_key"],
                       "endpointId": ep["endpoint_id"],
                       "url": ep["url"], "how": "Public directory listing; open folders by date to find files."})
    if (ascpr := ascpr_route(record)):
        routes.append(ascpr)
    routes = [r for r in routes if _allowed(r["url"])]
    if not routes:     # decided after the host filter, so filtered-out data routes still get documentation
        for url in record.get("sources", []):
            if _allowed(url):
                routes.append({"kind": "documentation", "label": "Documentation", "url": url,
                               "how": PI_DIRECTORY_HOW if _host(url) == PI_HOST else DOCUMENTATION_HOW})
    return routes
