# pip install xarray netCDF4 pandas numpy utide matplotlib requests obspy
import re
import numpy as np
import pandas as pd
import requests
import xarray as xr
import utide
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# The RCA's seafloor point current meters (VEL3D), with their EarthScope station (network OO) where it has one:
#   MAVS-4 (VEL3D-B, about 1 Hz): RS03INT2-MJ03D-12-VEL3DB304 International District (Gold Copy only), RS03AXBS-MJ03A-12-VEL3DB301
#     Axial Base (AXBA1), RS01SUM1-LJ01B-12-VEL3DB104 Southern Hydrate Ridge summit (HYS14), RS01SLBS-MJ01A-12-VEL3DB101 Slope Base (HYSB1)
#   Nortek Vector (VEL3D-C, 8 Hz): CE02SHBP-LJ01D-07-VEL3DC108 Oregon Shelf, 80 m (CZSHF), CE04OSBP-LJ01C-07-VEL3DC107 Oregon
#     Offshore, 580 m (CZOFF)
REFDES = "RS03INT2-MJ03D-12-VEL3DB304"
SOURCE = "goldcopy"      # "goldcopy": OOI's Gold Copy, with QARTOD results, beam values and (MAVS) pitch and roll for the
                         # cleaning; "earthscope": every sample from EarthScope, the same rotated velocities and quicker, but
                         # cleaned from the velocities alone (see the pitfalls: a failing MAVS gets through)
START, END = "2025-01-01", "2025-03-01"   # UTC; END is not included
SAMPLE_SECONDS = 10      # one sample is read every this many seconds (the files hold 1 or 8 a second)
AVERAGE = "1h"           # the averaging period
DROP = [4]               # QARTOD flags dropped (4 fail); add 3 to drop suspect
MAX_SPEED = 2.0          # m/s: a component beyond this is not a current (the MAVS writes 14.128 m/s when it fails)
MIN_CORRELATION = 70     # Vector only: a sample whose lowest beam correlation (%) is below this is dropped (the usual cut)
MAX_TILT_CHANGE = 5      # MAVS only: degrees; a sample whose pitch or roll is this far from the median is a garbled record
MIN_SHARE = 0.5          # an average needs this share of its samples, else it is blank
THREDDS = "https://thredds.dataexplorer.oceanobservatories.org/thredds"
EARTHSCOPE = {"RS03AXBS-MJ03A-12-VEL3DB301": ("AXBA1", "20"), "RS01SUM1-LJ01B-12-VEL3DB104": ("HYS14", "20"),
              "RS01SLBS-MJ01A-12-VEL3DB101": ("HYSB1", "20"), "CE02SHBP-LJ01D-07-VEL3DC108": ("CZSHF", "20"),
              "CE04OSBP-LJ01C-07-VEL3DC107": ("CZOFF", "21")}   # station, location
SPIKE_K, SPIKE_FLOOR = 6, 0.05   # EarthScope only: a sample this many robust SDs (and at least this many m/s) off its hour's median is a spike
MAX_HOUR_SPIKES = 0.1            # EarthScope only: an hour with more than this share of spikes is a failing instrument: all of it dropped

vector = "VEL3DC" in REFDES
stream = "vel3d_cd_velocity_data" if vector else "vel3d_b_sample"
prefix = "vel3d_c_" if vector else ""
comps = [f"{prefix}{c}_turbulent_velocity" for c in ("eastward", "northward", "upward")]
beams = [f"correlation_beam_{i}" for i in (1, 2, 3)] if vector else [f"velocity_beam_{b}" for b in "abcd"]
extra = beams + ([] if vector else ["pitch", "roll"])

# 1. The data, one sample in every SAMPLE_SECONDS. EarthScope: a day at a time (an 8 Hz month is 60 million values).
#    Gold Copy: the files overlapping the span (a Vector's folder also holds its system_data files), read over OPeNDAP,
#    with each velocity's QARTOD result.
start, end = pd.Timestamp(START), pd.Timestamp(END)
parts, broken, lat = [], [], None
if SOURCE == "earthscope":
    from obspy import UTCDateTime
    from obspy.clients.fdsn import Client
    from obspy.clients.fdsn.header import FDSNNoDataException
    match = [r for r in EARTHSCOPE if set(REFDES.upper().split("-")) <= set(r.split("-"))]
    if len(match) != 1:
        raise SystemExit(f"EarthScope has no station for {REFDES} (International District's MAVS is only in the Gold Copy): "
                         'set SOURCE = "goldcopy"')
    REFDES = match[0]
    sta, loc = EARTHSCOPE[REFDES]
    channels = ["MOU", "MOV", "MOW"] if vector else ["LOE", "LON", "LOZ"]   # east, north, up in m/s (gain 1)
    client = Client("https://service.earthscope.org")
    lat = client.get_stations(network="OO", station=sta, level="station")[0][0].latitude
    cols = {c: [] for c in channels}
    for day in pd.date_range(start.normalize(), end, freq="D", inclusive="left"):
        a, b = max(start, day), min(end, day + pd.Timedelta(days=1))
        try:
            st = client.get_waveforms("OO", sta, loc, ",".join(channels), UTCDateTime(a), UTCDateTime(b))
        except FDSNNoDataException:
            broken.append(f"{day:%Y-%m-%d}")
            continue
        st.merge(method=1, fill_value=None)
        for tr in st:
            x = pd.Series(np.ma.filled(np.ma.array(tr.data, dtype=float), np.nan),
                          index=pd.to_datetime(tr.times("timestamp"), unit="s"))
            cols[tr.stats.channel].append(x.resample(f"{SAMPLE_SECONDS}s").first())
    if broken:
        print(f"no EarthScope data from OO.{sta}.{loc} on:", ", ".join(broken))
    if all(cols.values()):
        parts.append(pd.DataFrame({c: pd.concat(cols[ch]) for c, ch in zip(comps, channels)}).dropna(how="all"))
else:
    folder = f"ooigoldcopy/public/{REFDES}-streamed-{stream}"
    listing = requests.get(f"{THREDDS}/catalog/{folder}/catalog.xml", timeout=120).text
    if "urlPath" not in listing:   # no such folder: a designator written short (CE04OSBP-LJ01C-VEL3DC107) is matched in full
        top = requests.get(f"{THREDDS}/catalog/ooigoldcopy/public/catalog.xml", timeout=120).text
        full = [t.split("-streamed-")[0] for t in re.findall(rf'title="([^"]+-streamed-{stream})"', top)
                if set(REFDES.upper().split("-")) <= set(t.split("-"))]
        if len(full) != 1:
            raise SystemExit(f"no Gold Copy {stream} folder for {REFDES}; name it in full ({', '.join(full) or 'none match'})")
        print(f"{REFDES} is {full[0]}")
        REFDES = full[0]
        folder = f"ooigoldcopy/public/{REFDES}-streamed-{stream}"
        listing = requests.get(f"{THREDDS}/catalog/{folder}/catalog.xml", timeout=120).text
    for path in sorted(set(re.findall(rf'urlPath="([^"]+{stream}_[^"]+\.nc)"', listing))):
        a, b = (pd.Timestamp(x[:15]) for x in re.search(r"_(\d{8}T\d{6})[\d.]*-(\d{8}T\d{6})[\d.]*\.nc$", path).groups())
        if b < start or a >= end:
            continue
        try:
            ds = xr.open_dataset(f"{THREDDS}/dodsC/{path}")
            rate = ds.sizes["obs"] / max((b - a).total_seconds(), 1)
            names = comps + [f"{c}_qartod_results" for c in comps if f"{c}_qartod_results" in ds] + [v for v in extra if v in ds]
            sub = ds[names].isel(obs=slice(None, None, max(1, round(SAMPLE_SECONDS * rate))))
            parts.append(sub.swap_dims({"obs": "time"}).sel(time=slice(start, end)).to_dataframe()[names])
            if lat is None and "lat" in ds:
                lat = float(ds["lat"].values.ravel()[0])
        except OSError:   # a few Gold Copy files fail on the server (DAP error 500)
            broken.append(f"{a:%Y-%m-%d}-{b:%Y-%m-%d}")
    if broken:
        print("unreadable Gold Copy files (a gap in what follows):", ", ".join(broken))
if not parts:
    raise SystemExit(f"no {stream} in the {SOURCE} for {REFDES} from {START} to {END}")
df = pd.concat(parts).sort_index()
df = df[~df.index.duplicated() & (df.index >= start) & (df.index < end)]
step = df.index.to_series().diff().median().total_seconds()
print(f"{len(df)} samples, one every {step:.0f} s, {df.index[0]} to {df.index[-1]}")

# 2. Quality: QARTOD flags, a gross range, and (Vector) beam correlation; a sample failing any is dropped whole.
bad = pd.Series(False, index=df.index)
for c in comps:
    q = f"{c}_qartod_results"
    if q in df:
        print(f"  {c} QARTOD: {df[q].value_counts().sort_index().to_dict()}")
        bad |= df[q].isin(DROP)
gross = (df[comps].abs() > MAX_SPEED).any(axis=1)
print(f"  dropped: {f'{bad.sum()} by QARTOD {DROP}, ' if SOURCE == 'goldcopy' else ''}{gross.sum()} beyond {MAX_SPEED} m/s", end="")
bad |= gross
if SOURCE == "earthscope":   # no beam values or pitch and roll: spikes against the hour's running median, and whole hours
    # where the spikes are many (a failing MAVS's garbled samples come in runs)
    x = df[comps].where(~bad, axis=0)
    n = max(4, round(3600 / step))
    med = x.rolling(n, center=True, min_periods=n // 4).median()
    mad = (x - med).abs().rolling(n, center=True, min_periods=n // 4).median() * 1.4826
    spike = ((x - med).abs() > (SPIKE_K * mad).clip(lower=SPIKE_FLOOR)).any(axis=1)
    failing = spike.groupby(df.index.floor("1h")).transform("mean") > MAX_HOUR_SPIKES
    print(f", {spike.sum()} spikes, {(failing & ~spike & ~bad).sum()} more in hours with over {MAX_HOUR_SPIKES:.0%} spikes", end="")
    bad |= spike | failing
    if failing.groupby(df.index.floor("1h")).first().mean() > 0.05 or (gross.mean() > 0.01):
        print("\nWARNING: many spiky hours or impossible speeds: the instrument may be failing, which EarthScope's velocities "
              "alone do not show (a railed MAVS beam gives smooth, wrong currents): rerun with SOURCE = \"goldcopy\"", end="")
elif vector:
    weak = df[beams].min(axis=1) < MIN_CORRELATION
    print(f", {weak.sum()} with a beam correlation under {MIN_CORRELATION} %", end="")
    bad |= weak
else:   # QARTOD passes these: a beam railed at the counter's limit (about -32316), or pitch and roll jumping 30 degrees
    railed = (df[beams].abs() >= 30000).any(axis=1)
    garbled = ((df["pitch"] - df["pitch"].median()).abs() > MAX_TILT_CHANGE) | \
              ((df["roll"] - df["roll"].median()).abs() > MAX_TILT_CHANGE)
    print(f", {railed.sum()} with a railed beam, {(garbled & ~railed).sum()} more with pitch or roll off by over "
          f"{MAX_TILT_CHANGE} degrees", end="")
    bad |= railed | garbled
print(f"; {100 * (1 - bad.mean()):.1f} % kept")
v = df.loc[~bad, comps].set_axis(["u", "v", "w"], axis=1)
if SOURCE == "goldcopy" and not vector:
    print(f"  pitch {df['pitch'].median():.1f}, roll {df['roll'].median():.1f} degrees (median): a tilted head mixes "
          "some horizontal flow into w")

# 3. Averages (blank when under MIN_SHARE of the samples remain), speed and the direction the current flows toward.
mean = v.resample(AVERAGE).mean()
expected = pd.Timedelta(AVERAGE).total_seconds() / step
mean[v["u"].resample(AVERAGE).count() < MIN_SHARE * expected] = np.nan
mean["speed"] = np.hypot(mean["u"], mean["v"])
mean["direction_to"] = np.degrees(np.arctan2(mean["u"], mean["v"])) % 360
print(f"{mean['u'].notna().mean() * 100:.0f} % of the {AVERAGE} averages filled; mean flow "
      f"{np.hypot(mean['u'].mean(), mean['v'].mean()) * 100:.2f} cm/s toward "
      f"{np.degrees(np.arctan2(mean['u'].mean(), mean['v'].mean())) % 360:.0f} degrees; speed median "
      f"{mean['speed'].median() * 100:.2f}, 95th percentile {mean['speed'].quantile(0.95) * 100:.2f} cm/s; "
      f"w mean {mean['w'].mean() * 100:.2f} cm/s")

# 4. Principal axis (the direction of most variance) and the tides: UTide fitted to the hourly u and v (a month
#    or more separates M2 from S2, a year K1 from P1), and the subtidal flow (Godin 24-24-25 h low-pass).
hourly = v.resample("1h").mean()
hourly[v["u"].resample("1h").count() < MIN_SHARE * 3600 / step] = np.nan
ok = hourly.dropna()
cov = np.cov(ok["u"] - ok["u"].mean(), ok["v"] - ok["v"].mean())
values, vectors = np.linalg.eigh(cov)
axis = np.degrees(np.arctan2(vectors[0, 1], vectors[1, 1])) % 180
print(f"principal axis {axis:.0f}-{axis + 180:.0f} degrees, holding {100 * values[1] / values.sum():.0f} % of the variance")
for c in ("u", "v"):   # gaps of up to 6 hours are bridged first; the filter needs 71 hours in a row
    filled = hourly[c].interpolate(limit=6, limit_area="inside")
    hourly[f"{c}_subtidal"] = (filled.rolling(24, center=True).mean().rolling(24, center=True).mean()
                               .rolling(25, center=True).mean())
tides = pd.DataFrame()
if len(ok) >= 15 * 24:
    coef = utide.solve(ok.index, ok["u"].to_numpy(), ok["v"].to_numpy(), lat=lat or 45.0, method="ols",
                       conf_int="linear", trend=False, verbose=False)
    tides = pd.DataFrame({"constituent": coef["name"], "major_m_s": coef["Lsmaj"], "minor_m_s": coef["Lsmin"],
                          "inclination_deg": coef["theta"], "phase_deg": coef["g"], "major_ci": coef["Lsmaj_ci"]})
    tide = utide.reconstruct(ok.index, coef, verbose=False)
    share = 1 - (np.var(ok["u"] - tide.u) + np.var(ok["v"] - tide.v)) / (np.var(ok["u"]) + np.var(ok["v"]))
    print(f"tides hold {100 * share:.0f} % of the hourly variance; largest: " + ", ".join(
        f"{r.constituent} {r.major_m_s * 100:.2f} cm/s along {r.inclination_deg:.0f} (minor {r.minor_m_s * 100:+.2f})"
        for r in tides.nlargest(4, "major_m_s").itertuples()))
else:
    print("under 15 days of hourly means: no tidal fit")

name = f"{REFDES}_{START}_{END}"
mean.rename_axis("time_utc").to_csv(name + f"_{AVERAGE}.csv", float_format="%.5f")
if len(tides):
    tides.to_csv(name + "_tides.csv", index=False, float_format="%.5f")

# 5. Plot: speed and components with the subtidal flow; the hourly velocities with the principal axis; the
#    progressive vector diagram (where a parcel moving with this flow would go).
fig = plt.figure(figsize=(12, 9))
s = fig.add_subplot(3, 2, (1, 2))
c = fig.add_subplot(3, 2, (3, 4), sharex=s)
s.plot(mean.index, mean["speed"] * 100, "k", lw=0.6, label=f"speed ({AVERAGE})")
s.plot(hourly.index, np.hypot(hourly["u_subtidal"], hourly["v_subtidal"]) * 100, "r", lw=1, label="subtidal")
s.set_ylabel("cm/s")
s.legend(loc="upper left", fontsize=8)
s.set_title(f"{REFDES} ({'Gold Copy, QARTOD ' + str(DROP) if SOURCE == 'goldcopy' else 'EarthScope, spikes'} "
            f"and beyond {MAX_SPEED} m/s dropped)", fontsize=10)
for col, color in (("u", "tab:blue"), ("v", "tab:orange")):
    c.plot(mean.index, mean[col] * 100, color=color, lw=0.5, label=f"{'east' if col == 'u' else 'north'}")
    c.plot(hourly.index, hourly[f"{col}_subtidal"] * 100, color=color, lw=1.4)
c.axhline(0, color="0.6", lw=0.6)
c.set_ylabel("cm/s (thick: subtidal)")
c.legend(loc="upper left", fontsize=8)
for ax in (s, c):
    ax.tick_params(axis="x", labelrotation=30)
h = fig.add_subplot(3, 2, 5)
h.plot(ok["u"] * 100, ok["v"] * 100, ".", ms=1, color="0.5")
r = 2 * np.sqrt(values[1]) * 100
mu, mv = ok["u"].mean() * 100, ok["v"].mean() * 100
h.plot([mu - r * np.sin(np.radians(axis)), mu + r * np.sin(np.radians(axis))],
       [mv - r * np.cos(np.radians(axis)), mv + r * np.cos(np.radians(axis))], "r", lw=1.5)
h.set_xlabel("east (cm/s)")
h.set_ylabel("north (cm/s)")
h.set_aspect("equal", "datalim")
p = fig.add_subplot(3, 2, 6)
km = ok[["u", "v"]].fillna(0).cumsum() * 3600 / 1000
path = p.scatter(km["u"], km["v"], c=(ok.index - ok.index[0]).days, s=1, cmap="viridis")
p.set_xlabel("east (km)")
p.set_ylabel("north (km)")
p.set_aspect("equal", "datalim")
fig.colorbar(path, ax=p, label="days")
fig.tight_layout()
fig.savefig(name + ".png", dpi=130)
