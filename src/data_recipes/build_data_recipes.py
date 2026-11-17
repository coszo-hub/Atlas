#!/usr/bin/env python3
"""Download recipes: for every instrument the atlas maps, the easiest way to get its data, then the other ways.

Each recipe names the facts a script needs, read from the services themselves (dataset IDs, stream names, variables
and units, quality-flag meanings, coverage, sampling, file names and sizes), and a Python template whose START and
END are the asked timeframe, so the answer model can write a script for one dataset and timeframe without guessing.

  --refresh  reads the services into runtime_data/DataRecipes/sources.json: OOI ERDDAP's catalog and each dataset's
             variables (and a one-day request, which measures its sampling); OOI's Gold Copy THREDDS catalog and each
             RCA dataset's files; the OOI raw-data archive's folder for each instrument (its years and newest files);
             EarthScope's channels for each station (and a one-minute waveform request); each PI data-portal directory
             (its layout and newest files); the FETCH repository's files.
  (default)  writes data/DataRecipes (one chunk per instrument) and src/atlas_worker/src/recipe_ids.json (every ID
             an instrument goes by -> its recipe chunk) from the cache and the atlas bundle.

The routes, easiest first for what most people want: EarthScope FDSN for seismometers and low-frequency hydrophones
(ObsPy reads waveforms directly); the raw-data archive for broadband hydrophones and cameras (their data are files);
ERDDAP for a table of processed data with quality flags; the Gold Copy for full-resolution NetCDF; the PI data portal
for PI instruments and experiments; GitHub for FETCH; OOI M2M (an account) for data newer than the Gold Copy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "src/atlas_map/public/atlas/sensors.json"
CACHE = ROOT / "runtime_data/DataRecipes/sources.json"
OUT = ROOT / "data/DataRecipes"
WORKER_IDS = ROOT / "src/atlas_worker/src/recipe_ids.json"
TESTS = ROOT / "runtime_data/DataRecipes/tests.json"          # each route's code and test window (test_recipes.py)
RESULTS = ROOT / "runtime_data/DataRecipes/test_results.json"  # what the sandbox run found

ERDDAP = "https://erddap.dataexplorer.oceanobservatories.org/erddap"
THREDDS = "https://thredds.dataexplorer.oceanobservatories.org/thredds"
GOLD = f"{THREDDS}/catalog/ooigoldcopy/public"
RAW = "https://rawdata.oceanobservatories.org/files"
FDSN = "https://service.earthscope.org"
M2M = "https://ooinet.oceanobservatories.org/api/m2m/12576/sensor/inv"
SITES = re.compile(r"^(?:RS|CE02SHBP|CE04OSBP|CE04OSPS|CE04OSPD)", re.I)
HEADERS = {"User-Agent": "RCA-Atlas data-recipes builder"}
# Instruments whose data are files rather than a table: broadband hydrophones (MiniSEED), cameras (stills, video),
# bio-acoustic sonar (echograms). Their raw-archive folder is the way to their data.
FILE_CLASSES = ("HYDBB", "CAMDS", "CAMHD", "ZPLSC")


def get(url: str, timeout: int = 120, method: str = "GET", tries: int = 3) -> tuple[int, str, dict]:
    """Status, text and headers; 404 and other client errors come back as their status, not an exception."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read() if method == "GET" else b""
                return r.status, body.decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == tries - 1:
                return e.code, "", dict(e.headers or {})
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                return 0, "", {}
        time.sleep(2 * (attempt + 1))
    return 0, "", {}


# Names read from remote listings go into code that people (and the recipe tests) run, so only plain names are kept:
# a name with a quote, a backslash or a parent folder is dropped, and every value enters the code through repr().
SAFE_NAME = re.compile(r"[A-Za-z0-9_+-][A-Za-z0-9._:+-]*/?")   # colons: OO-HYVM1--YDH-2026-10-27T00:00:00.000000Z.mseed
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+")


def links(page: str) -> list[str]:
    """The entries of an Apache or nginx directory listing, in listing order (sub-folders end in /), plain names only."""
    out = []
    for href in re.findall(r'href="([^"]+)"', page):
        href = html.unescape(href).removeprefix("./")
        if SAFE_NAME.fullmatch(href) and href not in out:
            out.append(href)
    return out


def sizes(page: str) -> dict[str, str]:
    """Each listed file's size as the listing prints it (832K, 32M)."""
    return {html.unescape(m[0]).removeprefix("./"): m[1]
            for m in re.findall(r'href="([^"?/][^"]*)">[^<]*</a>\s+\S+\s+\S+\s+([\d.]+[KMGT]?)\s', page)}


# --- refresh: read the services ---------------------------------------------------------------------------------

def refresh_erddap() -> dict:
    query = "datasetID,title,minTime,maxTime&datasetID=~%22ooi-(rs|ce02shbp|ce04osbp|ce04osps|ce04ospd).*%22"
    status, text, _ = get(f"{ERDDAP}/tabledap/allDatasets.csv?{query}")
    if status != 200:
        raise RuntimeError(f"ERDDAP catalog: HTTP {status}")
    out = {}
    for dataset_id, title, min_time, max_time in list(csv.reader(io.StringIO(text)))[2:]:
        status, info, _ = get(f"{ERDDAP}/info/{dataset_id}/index.csv")
        attrs, variables = {}, []
        for parts in list(csv.reader(io.StringIO(info)))[1:]:
            if parts[0] == "variable":
                variables.append(parts[1])
            elif parts[0] == "attribute":
                attrs[(parts[1], parts[2])] = parts[4]
        data_vars = [v for v in variables if v not in ("time", "latitude", "longitude", "z", "station")
                     and not v.endswith(("_qc_agg", "_qc_tests")) and re.fullmatch(r"[A-Za-z0-9_]+", v)]
        qc = [v.removesuffix("_qc_agg") for v in variables if v.endswith("_qc_agg")]
        flags = next(((attrs.get((v, "flag_values")), attrs.get((v, "flag_meanings"))) for v in variables
                      if v.endswith("_qc_agg") and attrs.get((v, "flag_meanings"))), (None, None))
        # One day ending at the newest data: the recipe's own request, which shows it works and how often it samples.
        end = datetime.fromisoformat(max_time.replace("Z", "+00:00"))
        start = end - timedelta(days=1)
        probe = data_vars[0] if data_vars else "time"
        url = (f"{ERDDAP}/tabledap/{dataset_id}.csv?time,{probe}"
               f"&time>={start:%Y-%m-%dT%H:%M:%SZ}&time<={end:%Y-%m-%dT%H:%M:%SZ}")
        status, body, _ = get(url, timeout=300)
        out[dataset_id] = {
            "title": title, "min_time": min_time, "max_time": max_time,
            "variables": [{"name": v, "long_name": attrs.get((v, "long_name")), "units": attrs.get((v, "units"))}
                          for v in data_vars],
            "flag_values": flags[0], "flag_meanings": flags[1], "qc": qc,
            "check": {"url": url, "status": status, "rows_per_day": max(0, len(body.strip().splitlines()) - 2)},
        }
        time.sleep(0.3)
    return out


def refresh_gold() -> dict:
    status, catalog, _ = get(f"{GOLD}/catalog.xml", timeout=300)
    if status != 200:
        raise RuntimeError(f"Gold Copy catalog: HTTP {status}")
    names = [n for n in re.findall(r'xlink:title="([^"]+)"', catalog) if SITES.match(n) and SAFE_ID.fullmatch(n) and n.count("-") >= 5]
    out = {}
    for name in names:
        status, xml, _ = get(f"{GOLD}/{name}/catalog.xml", timeout=300)
        files = []
        for block in re.findall(r"<dataset [^>]*urlPath=\"[^\"]+\.nc\"[^>]*>.*?</dataset>", xml, re.S):
            path = re.search(r'urlPath="([^"]+)"', block).group(1)
            span = re.search(r"_(\d{8}T\d{6})[.\d]*-(\d{8}T\d{6})[.\d]*\.nc$", path)
            size = re.search(r'<dataSize units="(\w+)">([\d.]+)<', block)
            if span and re.fullmatch(r"[A-Za-z0-9_./+-]+", path) and ".." not in path:
                files.append({"path": path, "first": span.group(1), "last": span.group(2),
                              "size": f"{size.group(2)} {size.group(1)}" if size else None})
        files.sort(key=lambda f: f["first"])
        check, variables = {}, []
        if files:
            status, das, _ = get(f"{THREDDS}/dodsC/{files[-1]['path']}.das")
            check = {"status": status}
            variables = das_variables(das)
        site, node, port, code, method, stream = name.split("-", 5)
        out[name] = {"refdes": f"{site}-{node}-{port}-{code}", "method": method, "stream": stream,
                     "files": len(files), "first": files[0]["first"] if files else None,
                     "last": files[-1]["last"] if files else None,
                     "newest_file": files[-1]["path"].rsplit("/", 1)[-1] if files else None,
                     "newest_size": files[-1]["size"] if files else None,
                     "largest_size": max((f["size"] for f in files if f["size"]), key=_bytes, default=None),
                     "variables": variables, "check": check}
        time.sleep(0.2)
    return out


# Variables every OOI stream carries that are not measurements: identifiers, the instrument's clocks, provenance, the
# per-test QC bits (each measured variable's flags are kept as <name>_qc_results).
NOT_MEASURED = re.compile(r"^(?:obs|time|lat|lon|deployment|id|provenance|date_time_string|time_sync_flag|DODS_EXTRA|sensor_id|"
                          r"\w*_timestamp|\w+_qc_executed|\w+_qc_results|\w+_qartod_executed|\w+_qartod_results)$")


def das_variables(das: str) -> list[dict]:
    """The measured variables in an OPeNDAP attribute response, with long name and units."""
    out = []
    for name, body in re.findall(r"^    ([A-Za-z0-9_]+) \{\n(.*?)^    \}", das, re.M | re.S):
        if NOT_MEASURED.match(name) or name == "NC_GLOBAL":
            continue
        units = re.search(r'String units "([^"]*)"', body)
        long_name = re.search(r'String long_name "([^"]*)"', body)
        out.append({"name": name, "long_name": long_name.group(1) if long_name else None,
                    "units": units.group(1) if units else None})
    # Processed values first: a raw count or an unprocessed (L0) value is what the processed ones are computed from.
    raw = lambda v: v["units"] in (None, "counts", "1") or "Unprocessed" in (v["long_name"] or "")
    return sorted(out, key=raw)


def parse_size(text: str | None) -> float:
    """Bytes in a directory listing's size (832K, 19M, 14G)."""
    m = re.fullmatch(r"([\d.]+)([KMGT]?)", text or "")
    return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}[m.group(2)] if m else 0


def _bytes(size: str | None) -> float:
    if not size:
        return 0
    value, unit = size.split()
    return float(value) * {"bytes": 1, "Kbytes": 1e3, "Mbytes": 1e6, "Gbytes": 1e9}.get(unit, 1)


# The time stamps raw file names carry, most specific first: (pattern, strptime format).
STAMPS = [(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "%Y-%m-%dT%H:%M:%S"), (r"\d{8}T\d{6}", "%Y%m%dT%H%M%S"),
          (r"\d{8}T\d{4}", "%Y%m%dT%H%M"), (r"\d{8}_\d{6}", "%Y%m%d_%H%M%S"), (r"\d{8}_\d{4}", "%Y%m%d_%H%M"),
          (r"D\d{8}-T\d{6}", "D%Y%m%d-T%H%M%S")]   # the last: echosounder files, ZPLSCB101-D20261027-T005054.raw
# Files beside the data that a download should not lead with: indexes, bottom picks, logs.
SIDE_FILES = ("idx", "bot", "log", "txt", "md5")


def stamp_of(name: str) -> tuple[str, str] | None:
    """The pattern and format of the time stamp in a raw file name."""
    for pattern, fmt in STAMPS:
        m = re.search(pattern, name)
        if m:
            try:
                datetime.strptime(m.group(0), fmt)
                return pattern, fmt
            except ValueError:
                continue
    return None


def refresh_raw(refdes_list: list[str]) -> dict:
    """Each instrument's raw-archive folder (files/SITE/NODE/CODE, no port): its years, layout and newest files. The
    archive keeps files either in day folders (YYYY/MM/DD/, some in an addendum/ sub-folder: hydrophones, cameras) or
    in the month folder itself (YYYY/MM/, often one file a day)."""
    out, nodes = {}, {}
    for refdes in refdes_list:
        site, node, _, code = refdes.split("-")
        key = f"{site}/{node}"
        if key not in nodes:
            status, page, _ = get(f"{RAW}/{key}/")
            nodes[key] = links(page) if status == 200 else []
        folders = [f.rstrip("/") for f in nodes[key] if f.rstrip("/") == code or f.startswith(code + "-")]
        if code not in folders:
            continue
        base = f"{RAW}/{key}/{code}"
        years = [y.rstrip("/") for y in links(get(f"{base}/")[1]) if re.fullmatch(r"\d{4}/", y)]
        newest, layout, files, file_sizes = None, None, [], {}
        recent = []                                  # the newest months, newest first: four, then up to twelve back
        for year in reversed(years):                 # for an instrument whose newest months are empty (MASSPA301)
            recent += [(year, m.rstrip("/")) for m in reversed(links(get(f"{base}/{year}/")[1])) if re.fullmatch(r"\d{2}/", m)]
            if len(recent) >= 12:
                break
        for year, month in recent[:12]:
            status, page, _ = get(f"{base}/{year}/{month}/")
            entries = links(page)
            here = [f for f in entries if not f.endswith("/")]
            if here:
                newest, layout, files, file_sizes = f"{year}/{month}/", "month", here, sizes(page)
                break
            for day in reversed([d.rstrip("/") for d in entries if re.fullmatch(r"\d{2}/", d)][-3:]):
                for sub in ("", "addendum/"):
                    status, page, _ = get(f"{base}/{year}/{month}/{day}/{sub}")
                    found = [f for f in links(page) if not f.endswith("/")]
                    if found:
                        newest, layout, files, file_sizes = f"{year}/{month}/{day}/{sub}", "day", found, sizes(page)
                        break
                if files:
                    break
            if files:
                break
        check = {}
        if files:
            status, _, headers = get(f"{base}/{newest}{files[0]}", method="HEAD")
            check = {"status": status, "bytes": headers.get("Content-Length")}
        stamp = next((st for f in files[:6] if (st := stamp_of(f))), None)
        out[refdes] = {"folder": f"{key}/{code}", "siblings": [f for f in folders if f != code], "years": years,
                       "layout": layout, "newest": newest, "files_there": len(files), "sample": files[:6],
                       "sample_sizes": [file_sizes.get(f) for f in files[:6]], "stamp": stamp,
                       "extensions": sorted({f.rsplit(".", 1)[-1].lower() for f in files if "." in f}), "check": check}
        time.sleep(0.1)
    return out


def main_channel(channels: list[dict]) -> str | None:
    """A station's main channel for a recipe: a vertical, at the highest rate, of its latest epoch."""
    vertical = [c for c in channels if c["channel"].endswith("Z")] or channels
    if not vertical:
        return None
    return max(vertical, key=lambda c: (c["end"] or "9999", float(c["rate"] or 0)))["channel"]


def refresh_earthscope(stations: list[dict]) -> dict:
    """Each EarthScope station's channels, and a one-minute request on its main channel: a day ago for a station that
    is open, its last day for one that closed (AXCC2, 2018-2021)."""
    out = {}
    for route in stations:
        net, sta = route["network"], route["station"]
        if f"{net}.{sta}" in out or not (re.fullmatch(r"[A-Z0-9]{1,2}", net) and re.fullmatch(r"[A-Z0-9]{1,5}", sta)):
            continue
        status, text, _ = get(f"{FDSN}/fdsnws/station/1/query?net={net}&sta={sta}&level=channel&format=text")
        channels = []
        for line in text.splitlines()[1:]:
            p = line.split("|")
            if len(p) >= 17 and re.fullmatch(r"[A-Z0-9]{3}", p[3]) and re.fullmatch(r"[A-Z0-9]{0,2}", p[2]):
                channels.append({"location": p[2], "channel": p[3], "rate": p[14], "sensor": p[10],
                                 "start": p[15][:10], "end": (p[16] or "")[:10]})
        cha = route.get("channel") if re.fullmatch(r"[A-Z0-9]{3}", route.get("channel") or "") else main_channel(channels)
        if not channels or not cha:
            out[f"{net}.{sta}"] = {"channels": channels, "channel": None, "closed": None, "check": {"status": status}}
            continue
        ends = [c["end"] for c in channels if c["channel"] == cha]
        closed = None if any(not e for e in ends) else max(ends)
        last = datetime.fromisoformat(closed) if closed else datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        # A minute a day back, or further back when that minute has no data yet: on 2026-11-15 every OO station
        # answered 204 for the day before, and the recipes lost their EarthScope route though the archive held years.
        for days in (1, 3, 7, 14, 30):
            end = last - timedelta(days=days)
            url = (f"{FDSN}/fdsnws/dataselect/1/query?net={net}&sta={sta}&cha={cha}"
                   f"&starttime={end - timedelta(minutes=1):%Y-%m-%dT%H:%M:%S}&endtime={end:%Y-%m-%dT%H:%M:%S}")
            status, body, headers = get(url, timeout=120)
            if status == 200:
                break
            time.sleep(0.3)
        out[f"{net}.{sta}"] = {"channels": channels, "channel": cha, "closed": closed,
                               "window": [f"{end - timedelta(minutes=1):%Y-%m-%dT%H:%M:%S}", f"{end:%Y-%m-%dT%H:%M:%S}"],
                               "check": {"url": url, "status": status, "bytes": len(body) or headers.get("Content-Length")}}
        time.sleep(0.3)
    return out


DOC_FILE = re.compile(r"(?i)(?:readme|\.(?:pdf|txt|md|html?|docx?)$)")
# What a portal folder holds beside the data: a scratch or holding folder, Windows thumbnails, logs, parser status.
JUNK = re.compile(r"(?i)^(?:tmp|temp|purgatory|trash|old|test|debug)/$|^thumbs\.db$|\.(?:log|status|lock|tmp)$|^stacktrace")


def head_size(url: str) -> str | None:
    status, _, headers = get(url, method="HEAD")
    n = headers.get("Content-Length")
    return None if status != 200 or n is None else f"{int(n) / 1e9:.1f}G" if int(n) >= 1e9 else f"{int(n) / 1e6:.1f}M" \
        if int(n) >= 1e6 else f"{int(n) / 1e3:.0f}K" if int(n) >= 1e3 else str(int(n))


def portal_leaf(url: str, path: str = "", depth: int = 0) -> dict | None:
    """The newest folder under url that holds data files that are not empty, six levels and three tries down: a folder
    with year folders beside a README is read through its newest year, and an empty newest folder gives way to the one
    before it (COVIS-ENG's 2020/99 holds empty files)."""
    status, page, _ = get(url + path)
    entries = links(page)
    entries = [e for e in entries if not JUNK.search(e)]
    subdirs = [e for e in entries if e.endswith("/")]
    files = [e for e in entries if not e.endswith("/")]
    data = [f for f in files if not DOC_FILE.search(f)]
    if subdirs and not data and depth < 6:              # DAS25: 2026/01/28/south-100m/8Hz/
        for sub in list(reversed(subdirs))[:3]:
            found = portal_leaf(url, path + sub, depth + 1)
            if found:
                return found
    if data:
        sample = data[-3:]
        file_sizes = sizes(page)
        sample_sizes = [file_sizes.get(f) or head_size(url + path + f) for f in sample]
        if any(parse_size(x) > 0 for x in sample_sizes):
            return {"newest_path": path, "files_there": len(data), "sample": sample, "sample_sizes": sample_sizes}
    return None


def refresh_portal(urls: list[str]) -> dict:
    """Each PI data-portal directory: its entries, and its newest files that are not empty."""
    out = {}
    for url in dict.fromkeys(urls):
        status, page, _ = get(url)
        top = links(page)
        leaf = portal_leaf(url) or {"newest_path": "", "files_there": 0, "sample": [], "sample_sizes": []}
        out[url] = {"entries": len(top), "first_entries": top[:4], "last_entries": top[-4:], **leaf,
                    "check": {"status": 200 if leaf["sample"] else status}}
        time.sleep(0.3)
    return out


def refresh_github(urls: list[str]) -> dict:
    out = {}
    for url in dict.fromkeys(urls):
        m = re.match(r"https://github.com/([^/]+)/([^/]+)/tree/([0-9a-f]{40})/(.+)", url)
        if not m:
            continue
        owner, repo, sha, path = m.groups()
        status, text, _ = get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={sha}")
        entries = json.loads(text) if status == 200 else []
        out[url] = {"repo": f"{owner}/{repo}", "commit": sha, "path": path,
                    "files": [{"name": e["name"], "size": e.get("size"), "type": e["type"]} for e in entries
                  if SAFE_NAME.fullmatch(e["name"])][:200],
                    "check": {"status": status}}
    return out


def earthscope_stations(sensors: list[dict]) -> list[dict]:
    """The EarthScope stations to read: each route that names one, and each EarthScope station the atlas maps (a closed
    one is listed only as documentation)."""
    out = [a for s in sensors for a in s.get("access", []) if a["kind"] == "earthscope"]
    for s in sensors:
        m = re.fullmatch(r"EARTHSCOPE-([A-Z0-9]{1,2})-([A-Z0-9]{1,5})", s["id"])
        if m:
            out.append({"network": m.group(1), "station": m.group(2), "sensor": s["id"]})
    return out


def refresh(sensors: list[dict]) -> None:
    routes = lambda kind: [a for s in sensors for a in s.get("access", []) if a["kind"] == kind]
    refdes = sorted({c for s in sensors for c in [s.get("refdes"), *(s.get("aliases") or [])]
                     if c and re.fullmatch(r"(?:RS|CE)\d{2}[A-Z0-9]{4}-[A-Z0-9]{5}-[A-Z0-9]{2}-[A-Z0-9]{9}", c)})
    started = datetime.now(timezone.utc)
    print("ERDDAP ...", flush=True); erddap = refresh_erddap()
    print("Gold Copy ...", flush=True); gold = refresh_gold()
    print("raw archive ...", flush=True); raw = refresh_raw(refdes)
    print("EarthScope ...", flush=True); earthscope = refresh_earthscope(earthscope_stations(sensors))
    print("PI portal ...", flush=True); portal = refresh_portal([a["url"] for a in routes("pi_portal")])
    print("GitHub ...", flush=True); github = refresh_github([a["url"] for a in routes("repository")])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"retrieved_at": started.isoformat(timespec="seconds"), "erddap": erddap, "gold": gold,
                                 "raw": raw, "earthscope": earthscope, "portal": portal, "github": github}, indent=1))
    print(f"{len(erddap)} ERDDAP, {len(gold)} Gold Copy, {len(raw)} raw folders, {len(earthscope)} stations, "
          f"{len(portal)} portal directories, {len(github)} repository paths -> {CACHE}")


# --- build: one recipe chunk per instrument ---------------------------------------------------------------------

def day(stamp: str | None) -> str:
    """2014-08-29T20:59:49Z or 20140829T205949 as 2014-08-29."""
    if not stamp:
        return "?"
    s = stamp.replace("-", "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def every(rows_per_day: int) -> str:
    if rows_per_day <= 1:
        return "about one row a day or less"
    seconds = 86400 / rows_per_day
    return (f"one row about every {seconds:.0f} s" if seconds < 120 else f"one row about every {seconds / 60:.0f} min"
            if seconds < 7200 else f"one row about every {seconds / 3600:.0f} h")


def erddap_route(ds_id: str, ds: dict, refdes: str) -> tuple[str, str]:
    names = [v["name"] for v in ds["variables"]]
    shown = names[:2] or ["time"]
    variables = "; ".join(f"{v['name']} ({v['long_name'] or v['name']}{', ' + v['units'] if v['units'] and v['units'] != 'None' else ''})"
                          for v in ds["variables"][:30])
    flags = ""
    if ds.get("flag_meanings"):
        pairs = ", ".join(f"{v.strip()} {m}" for v, m in zip(ds["flag_values"].split(","), ds["flag_meanings"].split()))
        flags = (f" Variables with a QARTOD quality flag column X_qc_agg: {', '.join(ds.get('qc', [])[:30])}; its values: {pairs}."
                 if ds.get("qc") else "")
    rate = every(ds["check"]["rows_per_day"]) if ds["check"]["status"] == 200 else "sampling not measured"
    selected = ", ".join(repr(n) for n in ["time", *shown, *[f"{n}_qc_agg" for n in shown[:1] if n in ds.get("qc", [])]])
    text = (f"OOI ERDDAP: processed data with quality flags, as a table (CSV) or NetCDF; public, no login. Dataset {ds_id}, "
            f"{day(ds['min_time'])} to {day(ds['max_time'])}, {rate} (a one-day request on the check date returned "
            f"{ds['check']['rows_per_day']:,} rows). A request of up to a few months at this rate returns quickly; request a "
            f"longer span month by month.\nVariables: {variables}.{flags}\n"
            f"```python\n# pip install erddapy pandas\nfrom erddapy import ERDDAP\n\n"
            f'START, END = "2025-03-01T00:00:00Z", "2025-03-15T00:00:00Z"   # the timeframe, UTC\n'
            f'e = ERDDAP(server={ERDDAP!r}, protocol="tabledap", response="csv")\n'
            f'e.dataset_id = {ds_id!r}\n'
            f"e.variables = [{selected}]   # any of the Variables listed above, with time\n"
            f'e.constraints = {{"time>=": START, "time<=": END}}\n'
            f'df = e.to_pandas(index_col="time (UTC)", parse_dates=True)\n'
            f'df.to_csv({refdes!r} + f"_{{START[:10]}}_{{END[:10]}}.csv")\n```\n'
            f"The same table as one URL (CSV): {ERDDAP}/tabledap/{ds_id}.csv?time,{shown[0]}&time>=START&time<=END")
    return text, f"{ERDDAP}/tabledap/{ds_id}.html"


def gold_route(streams: list[tuple[str, dict]], refdes: str) -> tuple[str, str]:
    def described(g: dict) -> str:
        names = "; ".join(f"{v['name']} ({v['long_name'] or v['name']}{', ' + v['units'] if v['units'] else ''})"
                          for v in g.get("variables", [])[:20])
        return f" Variables: {names}." if names else ""
    listed = " ".join(f"Stream {name.split('-', 4)[4]}: {day(g['first'])} to {day(g['last'])}, {g['files']} files.{described(g)}"
                      for name, g in streams)
    name, first = streams[0]
    chosen = [v["name"] for v in first.get("variables", []) if re.fullmatch(r"[A-Za-z0-9_]+", v["name"])][:1]
    text = (f"OOI Gold Copy THREDDS: full-resolution data, every sample as recorded and processed; public, no login. "
            f"One dataset per stream ({refdes}-<method>-<stream>), in NetCDF files named "
            f"deploymentNNNN_<dataset>_<first sample>-<last sample>.nc. Read through OPeNDAP, a script takes only the "
            f"asked variables and times from the files that overlap the timeframe, so an hour arrives in seconds "
            f"however large the file. {listed}\n"
            f"```python\n# pip install requests xarray netCDF4\nimport re, requests, xarray as xr\n\n"
            f"DATASET = {name!r}\n"
            f"VARIABLES = {chosen!r}   # any of the stream's variables listed above\n"
            f'START, END = "2025-03-01T00:00:00", "2025-03-01T01:00:00"   # the timeframe, UTC\n'
            f"T = {THREDDS!r}\n"
            f'stamp = lambda t: t.replace("-", "").replace(":", "")[:15]\n'
            f'xml = requests.get(f"{{T}}/catalog/ooigoldcopy/public/{{DATASET}}/catalog.xml", timeout=120).text\n'
            f"paths = [p for p in re.findall(r'urlPath=\"([^\"]+\\.nc)\"', xml)\n"
            f"         if (s := re.search(r'_(\\d{{8}}T\\d{{6}})[.\\d]*-(\\d{{8}}T\\d{{6}})[.\\d]*\\.nc$', p))\n"
            f"         and s.group(2) >= stamp(START) and s.group(1) <= stamp(END)]\n"
            f"parts = []\nfor path in paths:\n"
            f'    ds = xr.open_dataset(f"{{T}}/dodsC/{{path}}")   # OPeNDAP: nothing is read until .load()\n'
            f'    ds = (ds.swap_dims({{"obs": "time"}}) if "obs" in ds.dims else ds).reset_coords()   # depth becomes a variable\n'
            f"    wanted = [v for v in VARIABLES if v in ds.variables]   # a file can lack one (the newest, not yet processed)\n"
            f"    if wanted:\n"
            f"        parts.append(ds[wanted].sel(time=slice(START, END)).load())\n"
            f"if not parts:\n"
            f'    raise SystemExit(f"no {{VARIABLES}} in {{DATASET}} between {{START}} and {{END}}")\n'
            f'data = xr.concat(parts, dim="time", data_vars="all", join="outer")   # what a file lacks is NaN\n'
            f'data.encoding.pop("unlimited_dims", None)\n'
            f'data.to_netcdf(f"{{DATASET}}_{{stamp(START)}}_{{stamp(END)}}.nc")   # or data.to_dataframe().to_csv(...)\n```')
    return text, f"{GOLD}/{name}/catalog.html"


def raw_route(raw: dict) -> tuple[str, str] | None:
    if not raw["stamp"] or raw["layout"] not in ("day", "month"):
        return None                                   # files with no time in their names cannot be picked by timeframe
    base = f"{RAW}/{raw['folder']}"
    pattern, fmt = raw["stamp"]
    data_exts = [e for e in raw["extensions"] if e not in SIDE_FILES] or raw["extensions"]
    ext = max(data_exts, key=lambda e: sum(n.lower().endswith("." + e) for n in raw["sample"])) if data_exts else None
    if not ext or not re.fullmatch(r"[a-z0-9]{1,8}", ext):
        return None
    sample = ", ".join(f"{n} ({s})" if s else n for n, s in zip(raw["sample"], raw["sample_sizes"]))
    siblings = f" Beside it: {', '.join(raw['siblings'])}." if raw["siblings"] else ""
    file_rx = r'href="\.?/?([A-Za-z0-9_+-][A-Za-z0-9._:+-]*\.' + re.escape(ext) + r')"'   # only plain file names
    if raw["layout"] == "day":
        where = (f"one folder a day, {base}/YYYY/MM/DD/ (files are in the day folder or its addendum/ sub-folder)")
        loop = ('day = START.replace(hour=0, minute=0, second=0) - timedelta(days=1)   # a file can start the day before\n'
                "while day <= END:\n"
                '    folders += [f"{BASE}/{day:%Y/%m/%d}/", f"{BASE}/{day:%Y/%m/%d}/addendum/"]\n'
                "    day += timedelta(days=1)\n")
    else:
        where = f"one folder a month, {base}/YYYY/MM/"
        loop = ("month = (START.replace(day=1) - timedelta(days=1)).replace(day=1)   # a file can start the month before\n"
                "while month <= END:\n"
                '    folders.append(f"{BASE}/{month:%Y/%m}/")\n'
                "    month = (month + timedelta(days=32)).replace(day=1)\n")
    big = max(raw["sample_sizes"], key=parse_size, default=None)
    warning = (f" Its files are large (up to {big} each): even a short timeframe downloads whole files." if parse_size(big) > 1e9 else "")
    text = (f"OOI raw-data archive: the instrument's original files; public, no login.{warning} Files are kept {where}, "
            f"years {raw['years'][0]}-{raw['years'][-1]}; {raw['newest'].rstrip('/')} holds {raw['files_there']} files, "
            f"such as {sample}. Each file's name gives the time it starts, so a script keeps the files from the one "
            f"covering the start of the timeframe to the last starting before its end.{siblings}\n"
            f"```python\n# pip install requests\nimport re, requests\nfrom datetime import datetime, timedelta\n\n"
            f"BASE = {base!r}\n"
            f"START, END = datetime(2025, 3, 1, 0, 0), datetime(2025, 3, 1, 1, 0)   # the timeframe, UTC\n"
            f"folders = []\n{loop}"
            f"files = []\nfor folder in folders:\n"
            f"    r = requests.get(folder, timeout=120)\n    if not r.ok:\n        continue\n"
            f"    for name in dict.fromkeys(re.findall({file_rx!r}, r.text)):\n"
            f"        t = re.search({pattern!r}, name)\n"
            f"        if t:\n            files.append((datetime.strptime(t.group(0), {fmt!r}), folder + name))\n"
            f"files.sort()\n"
            f"keep = [url for i, (t, url) in enumerate(files) if t < END and (i + 1 == len(files) or files[i + 1][0] > START)]\n"
            f"for url in keep:\n"
            f'    with requests.get(url, stream=True, timeout=600) as r, open(url.rsplit("/", 1)[-1], "wb") as out:\n'
            f"        for block in r.iter_content(1 << 20):\n            out.write(block)\n```")
    return text, f"{base}/"


def earthscope_route(station: str, info: dict, route: dict) -> tuple[str, str]:
    net, sta = station.split(".")
    current = [c for c in info["channels"] if not c["end"] or c["end"] >= (info.get("closed") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))]
    groups = {}
    for c in current or info["channels"]:
        groups.setdefault((c["location"] or "--", c["sensor"]), []).append(f"{c['channel']} {float(c['rate']):g} Hz")
    channels = "; ".join(f"location {loc}: {', '.join(dict.fromkeys(chs))} ({sensor})" for (loc, sensor), chs in groups.items())
    first = min((c["start"] for c in info["channels"]), default="?")
    span = f"from {first} to {info['closed']} (the station has closed)" if info.get("closed") else f"since {first}"
    recorded = "Channels it recorded" if info.get("closed") else "Channels now"
    example = (datetime.fromisoformat(info["closed"]) - timedelta(days=1)).strftime("%Y-%m-%d") if info.get("closed") else "2025-03-01"
    cha = route.get("channel") or "HHZ"
    # The channel's instrument code says what it measures: a seismometer (H) ground velocity, an accelerometer (N)
    # ground acceleration, a hydrophone or pressure gauge (D) pressure, in the response's own units (pascals).
    output, units = {"N": ("ACC", "ground acceleration in m/s**2"), "D": ("DEF", "pressure in pascals")}.get(
        cha[1:2], ("VEL", "ground velocity in m/s"))
    text = (f"EarthScope FDSN web services (formerly IRIS): seismic and hydrophone waveforms as MiniSEED, with the "
            f"instrument response; public, no login. Network {net}, station {sta}, {span}. {recorded}: {channels}.\n"
            f"```python\n# pip install obspy\nimport numpy as np\nfrom obspy import UTCDateTime\nfrom obspy.clients.fdsn import Client\n\n"
            f'client = Client({FDSN!r})\n'
            f't1, t2 = UTCDateTime("{example}T00:00:00"), UTCDateTime("{example}T01:00:00")   # the timeframe, UTC\n'
            f'st = client.get_waveforms({net!r}, {sta!r}, "*", {cha!r}, t1, t2)\n'
            f'inv = client.get_stations(network={net!r}, station={sta!r}, channel={cha!r}, starttime=t1, endtime=t2, level="response")\n'
            f"# Counts to {units}; leave this loop out for raw counts. The pre-filter tapers the spectrum off outside\n"
            f"# the band the instrument records (the flat part of its response, below Nyquist), where dividing by its tiny\n"
            f"# response would blow up noise.\n"
            f"for tr in st:\n"
            f'    f = np.logspace(-4, np.log10(tr.stats.sampling_rate / 2), 500)\n'
            f'    amp = np.abs(inv.get_response(tr.id, tr.stats.starttime).get_evalresp_response_for_frequencies(f, output="DEF"))\n'
            f"    flat = f[amp >= amp.max() / np.sqrt(2)]\n"
            f"    low = max(flat[0], 2 / (tr.stats.endtime - tr.stats.starttime))   # no lower than the record resolves\n"
            f"    high = min(flat[-1], 0.45 * tr.stats.sampling_rate)\n"
            f'    tr.detrend("linear")\n'
            f"    tr.remove_response(inventory=inv, output={output!r}, pre_filt=(low / 2, low, 0.8 * high, high), water_level=None)\n"
            f'st.write({f"{net}.{sta}.{cha}_"!r} + f"{{t1.date}}.mseed", format="MSEED")\n```\n'
            f"Without Python: curl -o {sta}.mseed \"{FDSN}/fdsnws/dataselect/1/query?net={net}&sta={sta}&cha={cha}"
            f"&starttime=START&endtime=END\" (times as 2025-03-01T00:00:00).")
    return text, f"{FDSN}/fdsnws/station/1/query?net={net}&sta={sta}&level=channel&format=text"


# The cabled absolute pressure gauges and VEL3D-B current meters on EarthScope (atlas_map_data.access.EARTHSCOPE_PRODUCTS).
# Their values are already in physical units: pascals, m/s and degrees C. The pressure channels' response says pascals
# to psia (gain 1.450377e-4), which the data do not follow (Slope Base reads 29.6e6, its 2,900 m of water in pascals),
# so the scripts leave out remove_sensitivity, which would divide them by 1.45e-4. Checked 2026-11-16 in the sandbox:
# the pressure across Slope Base's UDO-to-LDO change (2018-06-26 10:00), and the currents against the Gold Copy's
# rotated velocities (one-minute means identical at Axial Base on 2025-03-01, within 1.5 mm/s at Slope Base, rotation
# 0.0 degrees). ERDDAP's means match east and up, not north, which there is the uncorrected magnetic-frame value.
# What is particular to each VEL3D-C at EarthScope.
VEL3DC_NOTES = {
    "CZSHF": ("EarthScope lists this instrument's deployments since September 2014 (the epochs above) and holds its data "
              "for parts of them (readings on 1 June 2015 and 1 January 2024, none on 1 June 2020 or 15 August 2026), so "
              "an asked timeframe may come back empty; OOI ERDDAP's copy ends in March 2024. "),
    "CZOFF": "EarthScope lists this instrument's deployments since August 2014 (the epochs above); OOI ERDDAP's copy ends on 1 October 2026. ",
}
PRODUCT_EXAMPLE = {"pressure": ("2025-03-01T00:00:00", "2025-03-02T00:00:00"), "currents": ("2025-03-01T00:00:00", "2025-03-01T06:00:00"),
                   "currents_c": ("2026-09-01T00:00:00", "2026-09-01T01:00:00")}
# The Oregon Shelf benthic package's Nortek Vector (VEL3D-C) at OO.CZSHF location 20: 13 deployment epochs from 10 Sep 2014,
# with data for parts of them (1 Jun 2015 and 1 Jan 2024, not 1 Jun 2020 or 15 Aug 2026); MOU, MOV and MOW at 8 Hz, LKO
# at 1 Hz. The station metadata gives MOU azimuth 90, MOV 0 and MOW dip -90, m/s with gain 1; checked
# 2026-11-16 in the sandbox (1 Sep 2026: -0.26 to 0.19 m/s, 8.51 C). Unlike the VEL3D-B there is no Gold Copy to say
# whether north is true or magnetic, so the recipe says the axes are the metadata's. EarthScope's copy ran about a week
# behind (10 Nov 00:00 on 16 Nov).


def product_epochs(info: dict, loc: str, codes: list[str]) -> str:
    rows = sorted({(c["channel"], c["start"], c["end"]) for c in info["channels"] if c["location"] == loc and c["channel"] in codes},
                  key=lambda r: (r[1], r[0]))
    rates = {c["channel"]: float(c["rate"]) for c in info["channels"] if c["location"] == loc}
    spans = {}
    for cha, start, end in rows:
        a, b = spans.get(cha, (start, end))
        spans[cha] = (min(a, start), "" if not end or not b else max(b, end))
    return "; ".join(f"{cha} ({rates[cha]:g} Hz) {a} to {b or 'now'}" for cha, (a, b) in sorted(spans.items(), key=lambda x: x[1][0]))


def earthscope_product_route(route: dict, info: dict) -> tuple[str, str]:
    net, sta, loc, product = route["network"], route["station"], route["location"], route["product"]
    t1, t2 = PRODUCT_EXAMPLE[product]
    head = (f"EarthScope FDSN web services: every sample as MiniSEED, public, no login. Network {net}, station {sta}, "
            f"location {loc}. ")
    if product == "pressure":
        epochs = product_epochs(info, loc, ["UDO", "LDO"])
        text = (head + f"Absolute pressure: {epochs}; each with its housing temperature (UK1 with UDO, LK1 with LDO). "
                "The script finds which channel recorded the asked timeframe and downloads each over its own part, so a "
                "timeframe across a change of channel gets both. The values are already pascals: the metadata's response "
                "says pascals to psia, which the data do not follow, so do not remove the sensitivity or response "
                "(it would divide the pascals by 1.45e-4). Source: https://coszo.org/absolute-seafloor-pressure.html\n"
                f"```python\n# pip install obspy pandas\nimport pandas as pd\nfrom obspy import UTCDateTime\n"
                f"from obspy.clients.fdsn import Client\n\nclient = Client({FDSN!r})\nNET, STA, LOC = {net!r}, {sta!r}, {loc!r}\n"
                f't1, t2 = UTCDateTime("{t1}"), UTCDateTime("{t2}")   # the timeframe, UTC\n'
                'TEMPERATURE = {"UDO": "UK1", "LDO": "LK1"}   # each pressure channel\'s housing temperature\n\n'
                '# Which pressure channel recorded which part of the timeframe (UDO every 15 s, LDO at 1 Hz).\n'
                'inv = client.get_stations(network=NET, station=STA, location=LOC, channel="UDO,LDO", starttime=t1, endtime=t2, level="channel")\n'
                "parts = []\n"
                "for cha in inv[0][0]:\n"
                "    a, b = max(t1, cha.start_date), min(t2, cha.end_date) if cha.end_date else t2\n"
                "    if a >= b:\n        continue\n"
                '    st = client.get_waveforms(NET, STA, LOC, f"{cha.code},{TEMPERATURE[cha.code]}", a, b)\n'
                "    st.merge(method=1, fill_value=None)\n"
                "    # Already pascals and degrees C: no remove_sensitivity or remove_response (see above).\n"
                "    columns = {}\n"
                "    for tr in st:\n"
                '        name = "pressure_pa" if tr.stats.channel == cha.code else "housing_temperature_c"\n'
                '        t = pd.to_datetime(tr.times("timestamp"), unit="s", utc=True).round("s")\n'
                "        columns[name] = pd.Series(tr.data.astype(float), index=t)\n"
                "    df = pd.DataFrame(columns)\n"
                '    df["channel"] = cha.code\n'
                "    parts.append(df)\n"
                '    print(f"{cha.code} ({cha.sample_rate:g} Hz): {a} to {b}, {len(df)} samples")\n\n'
                "data = pd.concat(parts).sort_index()\n"
                'data.index.name = "time_utc"\n'
                'out = f"{NET}.{STA}.{LOC}_pressure_{t1.date}_{t2.date}.csv"\n'
                "data.to_csv(out)\n"
                'print(f"wrote {out}: {len(data)} rows, {data.pressure_pa.min():.0f} to {data.pressure_pa.max():.0f} Pa")\n```')
    elif product == "currents_c":
        epochs = product_epochs(info, loc, ["MOU", "MOV", "MOW", "LKO"])
        text = (head + f"Point current meter (VEL3D-C, Nortek Vector): {epochs}; MOU, MOV and MOW are east, north and up "
                "velocity in m/s at 8 samples a second (the station metadata's azimuths 90 and 0 and dip -90; whether "
                "north is true or magnetic is not stated), LKO the water temperature in degrees C at 1 Hz (the response's "
                "gain is 1, so the values are already in these units). "
                + VEL3DC_NOTES.get(sta, "") +
                "EarthScope does not yet have these channels day by day (in November 2026 the Shelf's arrived about a "
                "week late), but is to. "
                "The script drops only values faster than 5 m/s, keeps the 8 Hz samples, and also writes one-minute means. "
                "Source: https://coszo.org/current-meter.html\n"
                f"```python\n# pip install obspy pandas numpy\nimport numpy as np\nimport pandas as pd\nfrom obspy import UTCDateTime\n"
                f"from obspy.clients.fdsn import Client\n\nclient = Client({FDSN!r})\nNET, STA, LOC = {net!r}, {sta!r}, {loc!r}\n"
                f't1, t2 = UTCDateTime("{t1}"), UTCDateTime("{t2}")   # the timeframe, UTC\n'
                'NAMES = {"MOU": "east_m_s", "MOV": "north_m_s", "MOW": "up_m_s", "LKO": "temperature_c"}\n\n'
                'st = client.get_waveforms(NET, STA, LOC, ",".join(NAMES), t1, t2)\n'
                "st.merge(method=1, fill_value=None)   # gaps stay gaps\n"
                "columns = {}\n"
                "for tr in st:\n"
                '    t = pd.to_datetime(tr.times("timestamp"), unit="s", utc=True)\n'
                "    columns[NAMES[tr.stats.channel]] = pd.Series(np.ma.filled(np.ma.array(tr.data, dtype=float), np.nan), index=t)\n"
                'velocity = pd.DataFrame({k: v for k, v in columns.items() if k != "temperature_c"})\n'
                'velocity.index.name = "time_utc"\n'
                'for c in ["east_m_s", "north_m_s", "up_m_s"]:\n'
                "    velocity.loc[velocity[c].abs() > 5, c] = np.nan   # not a current: bad values the instrument wrote\n"
                'velocity["speed_m_s"] = np.hypot(velocity.east_m_s, velocity.north_m_s)\n'
                'velocity.to_csv(f"{NET}.{STA}.{LOC}_currents_8Hz_{t1.date}.csv")\n'
                'minute = velocity.resample("1min").mean()\n'
                'if "temperature_c" in columns:\n'
                '    minute["temperature_c"] = columns["temperature_c"].resample("1min").mean()\n'
                'minute["speed_m_s"] = np.hypot(minute.east_m_s, minute.north_m_s)\n'
                'minute.to_csv(f"{NET}.{STA}.{LOC}_currents_1min_{t1.date}.csv")\n'
                'print(f"{len(velocity)} samples; mean speed {minute.speed_m_s.mean():.3f} m/s over {len(minute)} minutes")\n```')
    else:
        epochs = product_epochs(info, loc, ["LOE", "LON", "LOZ", "LKO"])
        slope = (" At Slope Base the 1 Hz samples scatter widely (north often 0.3 to 1.5 m/s on a day in November "
                 "2026, and the one-minute means about 0.3 m/s north in ERDDAP too), so treat its currents with care."
                 if sta == "HYSB1" else "")
        text = (head + f"Point current meter (VEL3D-B): {epochs}; LOE, LON and LOZ are east, north and up velocity in "
                "m/s, LKO the water temperature in degrees C (the response's gain is 1, so the values are already in "
                "these units). They are the OOI Gold Copy's velocities, east and north already rotated to true north "
                "(identical one-minute means at Axial Base on 1 March 2025); ERDDAP's northward velocity is instead the "
                "uncorrected magnetic-frame value. EarthScope has no QC flags, beam values or pitch and roll, so the "
                "script drops only values faster than 5 m/s (Southern Hydrate Ridge has isolated 9.99 and 12 m/s), keeps "
                "the 1 Hz samples as they are, and also writes one-minute means; for QARTOD-cleaned hourly currents and "
                "tides, use the VEL3D task recipe, which reads the Gold Copy."
                f"{slope} Source: https://coszo.org/current-meter.html\n"
                f"```python\n# pip install obspy pandas numpy\nimport numpy as np\nimport pandas as pd\nfrom obspy import UTCDateTime\n"
                f"from obspy.clients.fdsn import Client\n\nclient = Client({FDSN!r})\nNET, STA, LOC = {net!r}, {sta!r}, {loc!r}\n"
                f't1, t2 = UTCDateTime("{t1}"), UTCDateTime("{t2}")   # the timeframe, UTC\n'
                'NAMES = {"LOE": "east_m_s", "LON": "north_m_s", "LOZ": "up_m_s", "LKO": "temperature_c"}\n\n'
                'st = client.get_waveforms(NET, STA, LOC, ",".join(NAMES), t1, t2)\n'
                "st.merge(method=1, fill_value=None)   # gaps stay gaps\n"
                "columns = {}\n"
                "for tr in st:\n"
                '    t = pd.to_datetime(tr.times("timestamp"), unit="s", utc=True).round("s")\n'
                "    columns[NAMES[tr.stats.channel]] = pd.Series(np.ma.filled(np.ma.array(tr.data, dtype=float), np.nan), index=t)\n"
                "df = pd.DataFrame(columns)\n"
                'df.index.name = "time_utc"\n'
                'for c in ["east_m_s", "north_m_s", "up_m_s"]:\n'
                "    df.loc[df[c].abs() > 5, c] = np.nan   # not a current: bad values the instrument wrote\n"
                'df["speed_m_s"] = np.hypot(df.east_m_s, df.north_m_s)\n'
                'df["direction_deg"] = np.degrees(np.arctan2(df.east_m_s, df.north_m_s)) % 360   # towards, clockwise from north\n'
                'df.to_csv(f"{NET}.{STA}.{LOC}_currents_1Hz_{t1.date}.csv")\n'
                'minute = df[["east_m_s", "north_m_s", "up_m_s", "temperature_c"]].resample("1min").mean()\n'
                'minute["speed_m_s"] = np.hypot(minute.east_m_s, minute.north_m_s)\n'
                'minute.to_csv(f"{NET}.{STA}.{LOC}_currents_1min_{t1.date}.csv")\n'
                'print(f"{len(df)} samples; mean speed {minute.speed_m_s.mean():.3f} m/s over {len(minute)} minutes")\n```')
    return text, f"{FDSN}/fdsnws/station/1/query?net={net}&sta={sta}&loc={loc}&level=channel&format=text"


def portal_route(url: str, label: str, info: dict) -> tuple[str, str]:
    sample = ", ".join(f"{n} ({s})" if s else n for n, s in zip(info["sample"], info["sample_sizes"]))
    where = f"{url}{info['newest_path']}" if info["newest_path"] else url
    big = max(info["sample_sizes"], key=parse_size, default=None)
    warning = f" Its files are large (up to {big} each)." if parse_size(big) > 1e9 else ""
    text = (f"{label}: a public directory of files, no login, at {url}.{warning} It lists {info['entries']} entries, from "
            f"{', '.join(info['first_entries'][:2])} to {', '.join(info['last_entries'][-2:])}; the newest files, in "
            f"{where}, are such as {sample or 'none listed'}. A script lists the folder and downloads the files whose "
            f"names fall in the timeframe.\n"
            f"```python\n# pip install requests\nimport re, requests\nfrom urllib.parse import urljoin\n\n"
            f'FOLDER = {where!r}\n'
            f'names = re.findall(r\'href="(?:\\./)?([A-Za-z0-9_+-][A-Za-z0-9._:+-]*)"\', requests.get(FOLDER, timeout=120).text)   # files, not folders\n'
            f"for name in names:   # keep the names whose date is in the timeframe\n"
            f'    with requests.get(urljoin(FOLDER, name), stream=True, timeout=600) as r, open(name, "wb") as f:\n'
            f"        for block in r.iter_content(1 << 20):\n            f.write(block)\n```")
    return text, url


def github_route(url: str, label: str, info: dict) -> tuple[str, str]:
    files = ", ".join(f"{f['name']}" for f in info["files"][:12])
    raw = f"https://raw.githubusercontent.com/{info['repo']}/{info['commit']}/{info['path']}"
    text = (f"{label}: files in the {info['repo']} GitHub repository at commit {info['commit'][:7]}, public. "
            f"{len(info['files'])} entries in {info['path']}: {files}.\n"
            f"```python\n# pip install requests\nimport requests\n\n"
            f'BASE = {raw!r}\n'
            f'name = {info["files"][0]["name"] if info["files"] else "FILE"!r}   # one of the files listed\n'
            f'open(name, "wb").write(requests.get(f"{{BASE}}/{{name}}", timeout=120).content)\n```')
    return text, url


def ascpr_route(route: dict) -> tuple[str, str]:
    """A bottom pressure recorder site's campaign visits (Cook et al., 2023): the script takes the visits that overlap
    the timeframe, since a timeframe between visits has no data, and says which visits there are when none does."""
    sta, files = route["station"], route["files"]
    visits = "; ".join(f"{f['start'][:16].replace('T', ' ')} to "
                       f"{f['end'][11:16] if f['end'][:10] == f['start'][:10] else f['end'][:16].replace('T', ' ')} UTC" for f in files)
    rows = "\n".join(f'    ({f["start"][:19].replace("T", " ")!r}, {f["end"][:19].replace("T", " ")!r}, {f["url"]!r}),' for f in files)
    first = files[0]
    text = (f"{route['label']}: station {sta} is a seafloor benchmark that an ROV occupied with an Absolute "
            f"Self-Calibrating Pressure Recorder for about 2 to 6 hours at a time, so its data are short visits, not a "
            f"continuous record: {visits}. A timeframe between visits has no data. The UC San Diego Library holds one "
            f"CSV a visit, public, no login ({route['url']}; cite {route['doi']}). Per the dataset's readme, each "
            f"row is time1, time2 (each gauge's timestamp, a MATLAB datenumber), pressure1, pressure2 (calibrated "
            f"absolute sea pressure at the benchmark surface, kPa, from two Paroscientific gauges), temperature1, "
            f"temperature2 (degrees C), with no header; ocean tides are not removed. The script downloads the visits "
            f"that overlap the timeframe and writes one CSV with UTC times.\n"
            f"```python\n# pip install pandas requests\nimport io\nimport pandas as pd\nimport requests\n\n"
            f'START, END = {first["start"][:10] + " 00:00"!r}, {first["end"][:10] + " 23:59"!r}   # UTC\n'
            f"# Station {sta}'s visits (first and last sample, UTC) and their files\n"
            f"VISITS = [\n{rows}\n]\n"
            f'NAMES = ["time1", "time2", "pressure1_kPa", "pressure2_kPa", "temperature1_C", "temperature2_C"]\n'
            f"t1, t2 = pd.Timestamp(START), pd.Timestamp(END)\n"
            f"parts = []\n"
            f"for a, b, url in VISITS:\n"
            f"    if pd.Timestamp(a) <= t2 and pd.Timestamp(b) >= t1:\n"
            f"        df = pd.read_csv(io.StringIO(requests.get(url, timeout=120).text), header=None, names=NAMES)\n"
            f"        for k in (\"time1\", \"time2\"):   # MATLAB datenumber: 719529 is 1970-01-01\n"
            f"            df[k] = pd.to_datetime((df[k] - 719529) * 86400, unit=\"s\").dt.round(\"ms\")\n"
            f"        parts.append(df[(df[\"time1\"] >= t1) & (df[\"time1\"] <= t2)])\n"
            f"if not parts:\n"
            f"    raise SystemExit(\"No {sta} visit in the timeframe; its visits are \" + \"; \".join(f\"{{a}} to {{b}}\" for a, b, _ in VISITS))\n"
            f"out = pd.concat(parts).rename(columns={{\"time1\": \"time1_utc\", \"time2\": \"time2_utc\"}})\n"
            f'out.to_csv("ascpr_{sta}_pressure.csv", index=False)\n'
            f'print(len(out), "rows", out["time1_utc"].min(), "to", out["time1_utc"].max())\n```')
    return text, route["url"]


def m2m_route(refdes: str, streams: list[tuple[str, dict]]) -> str:
    """OOI M2M: every stream, including data newer than the Gold Copy, for anyone with a free OOI account. The request
    turns off the notification email as OOI's own ooi-data-explorations does (email=None)."""
    site, node, sensor = refdes.split("-", 2)
    method, stream = (streams[0][1]["method"], streams[0][1]["stream"]) if streams else ("METHOD", "STREAM")
    return (f"OOI M2M API: the same streams as NetCDF, including data newer than the Gold Copy; needs a free "
            f"ooinet.oceanobservatories.org account (its User Profile gives an API Username and API Token, which the "
            f"script reads from the environment). OOI prepares the files after the request (it can take up to 20 "
            f"minutes), then serves them from a THREDDS catalog for that request; the request sends no notification email.\n"
            f"```python\n# pip install requests xarray netCDF4\n# export OOI_API_USERNAME=... OOI_API_TOKEN=...\n"
            f"import os, re, time, requests, xarray as xr\n\n"
            f'AUTH = (os.environ["OOI_API_USERNAME"], os.environ["OOI_API_TOKEN"])\n'
            f'M2M = {M2M!r}\n'
            f"SITE, NODE, SENSOR = {site!r}, {node!r}, {sensor!r}\n"
            f"METHOD, STREAM = {method!r}, {stream!r}   # GET M2M/SITE/NODE/SENSOR lists the methods; .../METHOD lists its streams\n"
            f'START, END = "2025-03-01T00:00:00.000Z", "2025-03-01T01:00:00.000Z"   # the timeframe, UTC\n'
            f'r = requests.get(f"{{M2M}}/{{SITE}}/{{NODE}}/{{SENSOR}}/{{METHOD}}/{{STREAM}}", auth=AUTH, timeout=300,\n'
            f'                 params={{"beginDT": START, "endDT": END, "format": "application/netcdf", "email": "None"}})\n'
            f"r.raise_for_status()\n"
            f'urls = r.json()["allURLs"]\n'
            f'status = next(u for u in urls if "async_results" in u) + "/status.txt"\n'
            f"for _ in range(400):   # until OOI has written the files\n"
            f"    if requests.get(status, timeout=60).ok:\n        break\n    time.sleep(3)\n"
            f'catalog = requests.get(next(u for u in urls if "thredds" in u), timeout=120).text\n'
            f"files = sorted(set(re.findall(r\"dataset=([^'\\\"&]+?\\.nc)\", catalog)))\n"
            f"parts = []\nfor path in files:\n"
            f'    name = path.rsplit("/", 1)[-1]\n'
            f'    with requests.get("https://opendap.oceanobservatories.org/thredds/fileServer/" + path, stream=True, timeout=600) as f, open(name, "wb") as out:\n'
            f"        for block in f.iter_content(1 << 20):\n            out.write(block)\n"
            f"    ds = xr.open_dataset(name)\n"
            f'    parts.append(ds.swap_dims({{"obs": "time"}}) if "obs" in ds.dims else ds)\n'
            f'data = xr.concat(parts, dim="time")\n'
            f'data.encoding.pop("unlimited_dims", None)\n'
            f'data.to_netcdf(f"{{SITE}}-{{NODE}}-{{SENSOR}}-{{STREAM}}_{{START[:10]}}.nc")\n```')


def raw_window(raw: dict) -> dict:
    """Ten minutes from the start of the newest folder's first file."""
    pattern, fmt = raw["stamp"]
    t = datetime.strptime(next(m.group(0) for n in raw["sample"] if (m := re.search(pattern, n))), fmt)
    return {"start": t.strftime("%Y-%m-%dT%H:%M:%S"), "end": (t + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")}


def tested_note(result: dict) -> str:
    if result.get("skipped"):          # a deployment-long Gold Copy file is not downloaded for the test
        return ""
    return f"\nTested {result['date']}: the script ran in a clean Python environment and wrote {result['wrote']}."


PLANNED_HOW = "All data streams will be available to download through EarthScope once all systems are operational."


def planned_recipe(sensor: dict) -> dict:
    """A planned COSZO sensor publishes nothing yet: its recipe says where its data will be, and gives no script."""
    route = sensor["access"][0]
    name, label = sensor["name"], sensor.get("refdes") or sensor["id"]
    station = route["label"].split("station ")[-1] if "station " in route["label"] else None
    text = (f"How to download {name} ({label}) data. It is a planned COSZO sensor"
            f"{' at ' + sensor['location'] if sensor.get('location') else ''}{', on EarthScope station ' + station if station else ''}, "
            f"and publishes no data yet. {route['how']} Until then there is no data to download and no download script.")
    return {"chunk_id": f"recipe_{sensor['id']}", "title": f"How to download {name} ({label}) data: recipes", "text": text,
            "ids": [i for i in dict.fromkeys([sensor["id"], sensor.get("refdes"), *(sensor.get("aliases") or [])]) if i],
            "sources": [{"source_id": "RECIPE-SOURCE-" + hashlib.sha256(route["url"].encode()).hexdigest()[:20],
                         "title": f"{name}: {route['label']}", "source_url": route["url"]}],
            "routes": [route["label"].split(":")[0]], "type": sensor.get("type"), "name": name, "label": label,
            "place": sensor.get("location"), "depth": sensor.get("depthRange") or sensor.get("depth"),
            "easiest": "planned: " + route["how"][0].lower() + route["how"][1:].rstrip("."), "easiest_kind": "planned",
            "until": "", "tests": []}


def recipe(sensor: dict, src: dict, retrieved: str, results: dict | None = None) -> dict | None:
    if (sensor.get("access") or [{}])[0].get("kind") == "planned":
        return planned_recipe(sensor)
    results = results or {}
    ids = [sensor["id"], sensor.get("refdes"), *(sensor.get("aliases") or [])]
    refdes = next((i for i in ids if i and re.fullmatch(r"(?:RS|CE)\d{2}[A-Z0-9]{4}-[A-Z0-9]{5}-[A-Z0-9]{2}-[A-Z0-9]{9}", i)), None)
    routes = []                                           # (rank, text, source url, test)
    access = sensor.get("access", [])
    station_routes = [a for a in access if a["kind"] == "earthscope"]
    own = re.fullmatch(r"EARTHSCOPE-([A-Z0-9]{1,2})-([A-Z0-9]{1,5})", sensor["id"])
    if own and not station_routes:
        station_routes = [{"network": own.group(1), "station": own.group(2)}]
    for a in station_routes:
        info = src["earthscope"].get(f"{a['network']}.{a['station']}")
        if a.get("product") and info and info.get("channels"):
            t1, t2 = PRODUCT_EXAMPLE[a["product"]]
            routes.append((0, *earthscope_product_route(a, info),
                           {"kind": "earthscope", "start": t1, "end": t2,
                            "summary": f"EarthScope station {a['network']}.{a['station']}, location {a['location']} ({a['product']})"}))
            continue
        if info and info.get("channel") and info["check"]["status"] == 200:
            route = {**a, "channel": a.get("channel") or info["channel"]}
            routes.append((0, *earthscope_route(f"{a['network']}.{a['station']}", info, route),
                           {"kind": "earthscope", "start": info["window"][0], "end": info["window"][1],
                            "summary": f"EarthScope station {a['network']}.{a['station']}, channel {route['channel']}"}))
    code = (refdes or "").split("-")[-1][:5]
    raw = src["raw"].get(refdes) if refdes else None
    if raw and raw["sample"] and raw["check"].get("status") == 200 and (made := raw_route(raw)):
        routes.append((1 if code in FILE_CLASSES else 5, *made, {"kind": "raw", **raw_window(raw), "file_sizes": raw["sample_sizes"],
                                                                 "summary": "the OOI raw-data archive (original files)"}))
    ds_id = f"ooi-{refdes.lower()}" if refdes else None
    if ds_id in src["erddap"] and src["erddap"][ds_id]["check"]["status"] == 200:
        last = datetime.fromisoformat(src["erddap"][ds_id]["max_time"].replace("Z", "+00:00"))
        ds = src["erddap"][ds_id]
        routes.append((2, *erddap_route(ds_id, ds, refdes),
                       {"kind": "erddap", "start": f"{last - timedelta(days=1):%Y-%m-%dT%H:%M:%SZ}", "end": f"{last:%Y-%m-%dT%H:%M:%SZ}",
                        "summary": f"OOI ERDDAP dataset {ds_id}, {day(ds['min_time'])} to {day(ds['max_time'])}", "until": day(ds["max_time"])}))
    streams = sorted(((n, g) for n, g in src["gold"].items() if g["refdes"] == refdes and g["files"]),
                     key=lambda x: (-x[1]["files"], x[0]))
    if streams:
        g = streams[0][1]
        last = datetime.strptime(g["last"], "%Y%m%dT%H%M%S")
        routes.append((3, *gold_route(streams, refdes),
                       {"kind": "gold", "start": f"{last - timedelta(hours=1):%Y-%m-%dT%H:%M:%S}", "end": f"{last:%Y-%m-%dT%H:%M:%S}",
                        "newest_size": g["newest_size"],
                        "summary": f"OOI Gold Copy stream {streams[0][0]}, {day(g['first'])} to {day(g['last'])}", "until": day(g["last"])}))
    for a in access:
        if a["kind"] == "pi_portal" and a["url"] in src["portal"] and src["portal"][a["url"]]["sample"]:
            routes.append((4, *portal_route(a["url"], a["label"], src["portal"][a["url"]]),
                           {"kind": "portal", "file_sizes": src["portal"][a["url"]]["sample_sizes"], "summary": f"the RCA PI data portal, {a['url']}"}))
        if a["kind"] == "ucsd_ascpr":
            f = a["files"][0]
            routes.append((4, *ascpr_route(a), {"kind": "ucsd", "start": f["start"][:19], "end": f["end"][:19],
                                                "summary": f"the UC San Diego Library (Cook et al., 2023), station {a['station']}'s visits"}))
        if a["kind"] == "repository" and a["url"] in src["github"] and src["github"][a["url"]]["files"]:
            routes.append((4, *github_route(a["url"], a["label"], src["github"][a["url"]]), {"kind": "github", "summary": f"GitHub, {a['url']}"}))
    for i, r in enumerate(routes):
        r[3]["id"] = f"{sensor['id']}#{r[3]['kind']}#{hashlib.sha256(r[2].encode()).hexdigest()[:8]}"
        r[3]["code"] = re.search(r"```python\n(.*?)```", r[1], re.S).group(1) if "```python" in r[1] else None
    routes = [(rank, text + tested_note(results[test["id"]]), url, test) if test["id"] in results else (rank, text, url, test)
              for rank, text, url, test in routes if results.get(test["id"], {}).get("passed", True)]
    if not routes and not refdes:
        return None
    routes.sort(key=lambda r: r[0])
    name, label = sensor["name"], refdes or sensor["id"]
    parts = [f"How to download {name} ({label}) data. Times are UTC; replace START and END (or the example dates) "
             f"with the asked timeframe. Each route was checked against its service on {retrieved[:10]}."]
    for i, (_, text, _, _) in enumerate(routes):
        parts.append(("Easiest: " if i == 0 else f"Also ({i + 1}): ") + text)
    # M2M queues each request and can take 20 minutes, and the Gold Copy holds the same streams to the previous day, so
    # its script is given only where no public route has the data; elsewhere it is one line.
    if refdes and not routes:
        done = results.get(f"{sensor['id']}#m2m")
        parts.append("Only route: " + m2m_route(refdes, streams) + (tested_note(done) if done and done["passed"] else ""))
    # Where the Gold Copy has the instrument, it is current to its newest file: say how far the data run, not M2M.
    if streams:
        newest = max(g["last"] for _, g in streams)
        parts.append(f"How recent: the Gold Copy's newest file for this instrument ends {day(newest)} "
                     f"{newest[9:11]}:{newest[11:13]} UTC (as of {retrieved[:10]}); it holds nothing later than that.")
    sources = [{"source_id": "RECIPE-SOURCE-" + hashlib.sha256(url.encode()).hexdigest()[:20], "title": title, "source_url": url}
               for title, url in [(f"{name}: {r[1].split(':', 1)[0]}", r[2]) for r in routes]
               + ([(f"OOI M2M sensor inventory for {refdes}", f"{M2M}/{'/'.join(refdes.split('-', 2))}")] if refdes else [])]
    return {"chunk_id": f"recipe_{sensor['id']}", "title": f"How to download {name} ({label}) data: recipes",
            "text": "\n\n".join(parts), "ids": [i for i in dict.fromkeys(ids) if i], "sources": sources,
            "routes": [r[1].split(":", 1)[0] for r in routes] + (["OOI M2M"] if refdes and not routes else []),
            "type": sensor.get("type"), "name": name, "label": label, "place": sensor.get("location"),
            "depth": sensor.get("depthRange") or sensor.get("depth"),
            "easiest": routes[0][3]["summary"] if routes else "OOI M2M only (a free OOI account; no public route has its data)",
            "easiest_kind": routes[0][3]["kind"] if routes else "m2m", "until": routes[0][3].get("until", "") if routes else "",
            "tests": [r[3] for r in routes] + ([{"id": f"{sensor['id']}#m2m", "kind": "m2m", "code": re.search(
                r"```python\n(.*?)```", m2m_route(refdes, streams), re.S).group(1), "needs_account": True}]
                if refdes and not routes else [])}


# What a reference designator's node (RS03AXPS-SF03A-...) says the instrument is on: a shallow profiler mooring carries
# instruments both on its 200 m platform (PC) and on the profiler that rises from it (SF).
MOUNTED_ON = {"LJ": "on a seafloor junction box", "MJ": "on a seafloor junction box", "LV": "on a seafloor junction box",
              "PN": "on a seafloor node", "PC": "fixed on the 200 m platform", "SF": "on the shallow profiler (moves 200 m to near the surface)",
              "DP": "on the deep profiler (moves through the water column)"}


ACRONYMS = {"ctd": "CTD", "adcp": "ADCP", "par": "PAR", "pco2": "pCO2", "ph": "pH", "hpies": "HPIES", "das": "DAS"}


def type_overviews(recipes: list[dict]) -> list[dict]:
    """For each instrument type, one chunk listing every instrument of it, where it is and its
    easiest route, for a download question that names the type and no place ("how do I download oxygen data?"). Its
    example is the recipe of a Regional Cabled Array instrument whose easiest route is the type's commonest, fixed (on a
    junction box or platform) before on a profiler, its data running latest."""
    groups = {}
    for r in recipes:
        if r.get("type"):
            groups.setdefault(r["type"], []).append(r)
    out = []
    for kind, members in sorted(groups.items()):
        members.sort(key=lambda r: (not r["label"].startswith("RS"), r["label"]))
        kinds = {m["easiest_kind"] for m in members} - ({"planned"} if any(m["easiest_kind"] != "planned" for m in members) else set())
        common = max(kinds, key=lambda k: sum(m["easiest_kind"] == k for m in members))
        example = min((m for m in members if m["easiest_kind"] == common),
                      key=lambda m: (not m["label"].startswith("RS"), m["label"][9:11] in ("SF", "DP"), "".join(chr(255 - ord(c)) for c in m["until"])))
        label = " ".join(ACRONYMS.get(w, w) for w in kind.split("_"))
        count = f"the {len(members)} {label} instruments" if len(members) > 1 else f"the one {label} instrument"
        planned = sum(m["easiest_kind"] == "planned" for m in members)
        if planned == len(members):
            are = "All are planned COSZO sensors and publish" if len(members) > 1 else "It is a planned COSZO sensor and publishes"
            lines = [f"Where to download {label} data: {count} the atlas maps, each with its place. {are} no data yet. {PLANNED_HOW}"]
        else:
            lines = [f"Where to download {label} data: {count} the atlas maps, each with its place "
                     f"and its easiest route. Each{' that publishes data' if planned else ''} has its own recipe with a tested "
                     f"Python script; the scripts of instruments with the same route differ only in their dataset ID or stream "
                     f"and variable names. The example recipe is {example['name']} ({example['label']})."]
        for m in members:
            d = m["depth"] if isinstance(m["depth"], list) else [m["depth"]] * 2 if isinstance(m["depth"], (int, float)) else None
            depth = "" if not d else f"{d[0]:g} m" if d[0] == d[1] else f"{d[0]:g}-{d[1]:g} m"
            mount = MOUNTED_ON.get(m["label"][9:11], "")
            lines.append(f"- {m['name']} ({m['label']}){', ' + m['place'] if m.get('place') else ''}"
                         f"{', ' + mount if mount else ''}{', ' + depth if depth else ''}: {m['easiest']}.")
        out.append({"chunk_id": f"recipe_type_{kind}", "title": f"Where to download {label} data: every {label} instrument",
                    "text": "\n".join(lines), "type": kind, "members": [m["chunk_id"] for m in members],
                    "example": example["chunk_id"],
                    # it lists many instruments, so it links to ERDDAP's list of the type's datasets, not one of them
                    "source_url": (f"{ERDDAP}/search/index.html?searchFor={urllib.parse.quote_plus(label)}&itemsPerPage=100"
                                   if common == "erddap" else example["sources"][0]["source_url"])})
    return out


def catalogued(sensors: list[dict]) -> list[dict]:
    """The bundle's instruments less the inventory's reference-only records (codes papers name, no instrument)."""
    inventory = ROOT / "data/Instruments/instruments.jsonl"
    reference = {r["canonical_id"] for r in map(json.loads, inventory.read_text().splitlines()) if r["record_status"] == "reference_only"}
    return [s for s in sensors if s["id"] not in reference]


def build() -> None:
    src = json.loads(CACHE.read_text())
    sensors = catalogued(json.loads(BUNDLE.read_text())["sensors"])
    results = json.loads(RESULTS.read_text())["results"] if RESULTS.exists() else {}
    recipes = [r for s in sensors if (r := recipe(s, src, src["retrieved_at"], results))]
    TESTS.write_text(json.dumps([{k: v for k, v in t.items() if k not in ("summary", "until")} for r in recipes for t in r["tests"]], indent=1))
    overviews = type_overviews(recipes)
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {s["source_id"]: {**s, "kind": "data_service"} for r in recipes for s in r["sources"]}
    # A recipe is cited as itself, linking to its easiest route; its routes' services are its graph neighbours.
    for r in recipes:
        sources[f"RECIPE-SOURCE-{r['chunk_id']}"] = {"source_id": f"RECIPE-SOURCE-{r['chunk_id']}", "title": r["title"],
                                                     "source_url": r["sources"][0]["source_url"], "kind": "data_recipe"}
    for o in overviews:
        sources[f"RECIPE-SOURCE-{o['chunk_id']}"] = {"source_id": f"RECIPE-SOURCE-{o['chunk_id']}", "title": o["title"],
                                                     "source_url": o["source_url"], "kind": "data_recipe"}
    chunks = [{"chunk_id": r["chunk_id"], "title": r["title"], "text": r["text"], "entity_ids": [f"RECIPE-{r['chunk_id']}"],
               "source_ids": [f"RECIPE-SOURCE-{r['chunk_id']}"], "source_urls": [r["sources"][0]["source_url"]]}
              for r in recipes] + [{"chunk_id": o["chunk_id"], "title": o["title"], "text": o["text"], "entity_ids": [f"RECIPE-{o['chunk_id']}"],
                                    "source_ids": [f"RECIPE-SOURCE-{o['chunk_id']}"], "source_urls": [o["source_url"]]} for o in overviews]
    entities = [{"entity_id": f"RECIPE-{r['chunk_id']}", "entity_type": "data_recipe", "name": r["title"],
                 "attributes": {"ids": r["ids"], "routes": r["routes"]}} for r in recipes]
    relationships_overview = [{"relationship_id": f"RECIPE-{o['chunk_id']}-LISTS-RECIPE-{c}", "source_id": f"RECIPE-{o['chunk_id']}",
                               "target_id": f"RECIPE-{c}", "relationship_type": "LISTS"} for o in overviews for c in o["members"]]
    entities += [{"entity_id": f"RECIPE-{o['chunk_id']}", "entity_type": "data_recipe_overview", "name": o["title"],
                  "attributes": {"type": o["type"], "members": o["members"], "example": o["example"]}} for o in overviews]
    relationships = [{"relationship_id": f"{e['entity_id']}-SOURCE-{src['source_id']}", "source_id": e["entity_id"],
                      "target_id": src["source_id"], "relationship_type": "DOWNLOADS_FROM"}
                     for e, r in zip(entities, recipes) for src in r["sources"]] + relationships_overview
    for name, rows in (("chunks", chunks), ("entities", entities), ("relationships", relationships),
                       ("source_documents", list(sources.values()))):
        (OUT / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    counts = {}
    for r in recipes:
        for route in r["routes"]:
            counts[route] = counts.get(route, 0) + 1
    (OUT / "manifest.json").write_text(json.dumps({
        "corpus": "RCA Atlas data download recipes", "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "services_checked_at_utc": src["retrieved_at"], "recipe_count": len(recipes), "type_overview_count": len(overviews), "routes": counts,
        "chunk_count": len(chunks), "entity_count": len(entities), "relationship_count": len(relationships),
        "source_document_count": len(sources)}, indent=2))
    ids = {}
    for r in recipes:
        for i in r["ids"]:
            ids.setdefault(i, r["chunk_id"])
    # TYPE:<id> is the overview of the instrument's type, EXAMPLE:<id> the recipe it gives as the type's example script.
    for o in overviews:
        for c in o["members"]:
            for i in next(r for r in recipes if r["chunk_id"] == c)["ids"]:
                ids.setdefault(f"TYPE:{i}", o["chunk_id"])
                ids.setdefault(f"EXAMPLE:{i}", o["example"])
    WORKER_IDS.write_text(json.dumps(dict(sorted(ids.items())), indent=0) + "\n")
    print(f"{len(recipes)} recipes, {len(overviews)} type overviews; routes {counts}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--refresh", action="store_true", help="read the services into the cache first")
    parser.add_argument("--refresh-raw", action="store_true", help="re-read only the raw-data archive")
    parser.add_argument("--refresh-gold", action="store_true", help="re-read only the Gold Copy")
    parser.add_argument("--refresh-erddap", action="store_true", help="re-read only ERDDAP")
    parser.add_argument("--refresh-portal", action="store_true", help="re-read only the PI data portal")
    parser.add_argument("--refresh-earthscope", action="store_true", help="re-read only EarthScope")
    args = parser.parse_args()
    if args.refresh:
        refresh(catalogued(json.loads(BUNDLE.read_text())["sensors"]))
    elif args.refresh_erddap:
        cache = json.loads(CACHE.read_text())
        cache["erddap"] = refresh_erddap()
        CACHE.write_text(json.dumps(cache, indent=1))
    elif args.refresh_gold:
        cache = json.loads(CACHE.read_text())
        cache["gold"] = refresh_gold()
        CACHE.write_text(json.dumps(cache, indent=1))
    elif args.refresh_earthscope:
        cache, sensors = json.loads(CACHE.read_text()), catalogued(json.loads(BUNDLE.read_text())["sensors"])
        cache["earthscope"] = refresh_earthscope(earthscope_stations(sensors))
        CACHE.write_text(json.dumps(cache, indent=1))
    elif args.refresh_portal:
        cache, sensors = json.loads(CACHE.read_text()), catalogued(json.loads(BUNDLE.read_text())["sensors"])
        cache["portal"] = refresh_portal([a["url"] for s in sensors for a in s.get("access", []) if a["kind"] == "pi_portal"])
        CACHE.write_text(json.dumps(cache, indent=1))
    elif args.refresh_raw:
        cache, sensors = json.loads(CACHE.read_text()), catalogued(json.loads(BUNDLE.read_text())["sensors"])
        cache["raw"] = refresh_raw(sorted({c for s in sensors for c in [s.get("refdes"), *(s.get("aliases") or [])]
                                           if c and re.fullmatch(r"(?:RS|CE)\d{2}[A-Z0-9]{4}-[A-Z0-9]{5}-[A-Z0-9]{2}-[A-Z0-9]{9}", c)}))
        CACHE.write_text(json.dumps(cache, indent=1))
    build()
