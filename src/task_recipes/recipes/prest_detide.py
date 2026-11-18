# pip install obspy pandas numpy gsw utide matplotlib
import copy
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import gsw
import utide
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoDataException

# The RCA's tidal seafloor pressure gauges (PREST, a Paroscientific quartz sensor), each recorded at a seismic station on
# EarthScope (network OO, location 10), as pascals of absolute pressure:
#   RS03AXBS-MJ03A-06-PRESTA301 Axial Base (AXBA1: UDO, every 15 s)
#   RS01SLBS-MJ01A-06-PRESTA101 Oregon Slope Base (HYSB1: UDO every 15 s to 26 June 2018, then LDO at 1 Hz)
#   RS01SUM1-LJ01B-09-PRESTB102 Southern Hydrate Ridge summit (HYS14: UDO to 11 August 2017, then LDO at 1 Hz)
REFDES = "RS01SLBS-MJ01A-06-PRESTA101"
START, END = "2025-01-01", "2025-04-01"  # UTC; END is not included
FIT_DAYS = 365                           # the tide is fitted to this many days ending at END (a year separates K1 from
                                         # P1 and S2 from K2; less leaves their beat in the residual)
GODIN = True                             # also the Godin low-pass (24, 24 and 25-hour running means), with no tide model
GAP_HOURS = 12                           # a gap this long may be a recovery and redeployment: the level across it is reported
GAUGES = {"RS03AXBS-MJ03A-06-PRESTA301": "AXBA1", "RS01SLBS-MJ01A-06-PRESTA101": "HYSB1", "RS01SUM1-LJ01B-09-PRESTB102": "HYS14"}
ATMOSPHERE_DBAR = 10.1325                # the gauge reads absolute pressure: sea pressure is this much less

match = [r for r in GAUGES if set(REFDES.upper().split("-")) <= set(r.split("-"))]
if len(match) != 1:
    raise SystemExit(f"{REFDES} is not one of the tidal pressure gauges: {', '.join(GAUGES)}")
REFDES, sta = match[0], GAUGES[match[0]]

# 1. Each pressure channel's part of the fit's span (the year before END, or the span asked for if longer), thirty days
#    a request, cut to one-minute means as it comes. The values are already pascals: the metadata's response says
#    pascals to psia, which the data do not follow, so the response is not removed.
client = Client("https://service.earthscope.org")
start, end = pd.Timestamp(START), pd.Timestamp(END)
fit_start = min(start, end - pd.Timedelta(days=FIT_DAYS))
inv = client.get_stations(network="OO", station=sta, location="10", channel="UDO,LDO", starttime=UTCDateTime(fit_start),
                          endtime=UTCDateTime(end), level="channel")
lat = inv[0][0].latitude
def fetch(code, a, b):
    """One request's one-minute means; an empty list when EarthScope has no data then."""
    try:
        st = Client("https://service.earthscope.org").get_waveforms("OO", sta, "10", code, UTCDateTime(a), UTCDateTime(b))
    except FDSNNoDataException:
        return a, []
    out = []
    for tr in st:
        x = pd.Series(tr.data.astype(float), index=pd.to_datetime(tr.times("timestamp"), unit="s"))
        out.append(x[x > 0].resample("1min").mean().dropna())
    return a, out


# A request costs from 5 to 40 s whatever its length (November 2026), so 30 days each, four at a time.
jobs = []
for cha in inv[0][0]:
    a0 = max(fit_start, pd.Timestamp(cha.start_date.datetime))
    b0 = min(end, pd.Timestamp(cha.end_date.datetime)) if cha.end_date else end
    edges = list(pd.date_range(a0, b0, freq="30D")) + [b0]
    jobs += [(cha.code, a, b) for a, b in zip(edges[:-1], edges[1:]) if a < b]
    print(f"{cha.code} ({cha.sample_rate:g} Hz): {a0:%Y-%m-%d} to {b0:%Y-%m-%d}", flush=True)
minutes, empty = [], []
with ThreadPoolExecutor(4) as pool:
    for a, got in pool.map(lambda job: fetch(*job), jobs):
        minutes += got
        if not got:
            empty.append(f"{a:%Y-%m-%d}")
if empty:
    print("30-day requests with no data, starting:", ", ".join(empty))
if not minutes:
    raise SystemExit(f"no pressure from OO.{sta}.10 between {fit_start:%Y-%m-%d} and {END}")
p = pd.concat(minutes).groupby(level=0).mean().sort_index()
p = p[(p.index >= fit_start) & (p.index < end)]
print(f"{len(p)} one-minute means, {p.index[0]} to {p.index[-1]} (the tide's fit; the products are for {START} to {END})")

# 2. Pressure to depth: sea pressure (absolute less one atmosphere, Pa to dbar), depth from TEOS-10 at the station's
#    latitude; hourly, keeping hours with at least half their minutes.
hourly = pd.DataFrame({"pressure_pa": p.resample("1h").mean()})
hourly[p.resample("1h").count() < 30] = np.nan
hourly["depth_m"] = -gsw.z_from_p(hourly["pressure_pa"].to_numpy() / 1e4 - ATMOSPHERE_DBAR, lat)

# 3. The tide: a harmonic fit (UTide, with a linear trend so a drift or slow motion does not leak into the tides) to the
#    hourly depths of the fit's span, predicted for the span asked for. Only the daily and faster tides are taken away:
#    the fortnightly, monthly and seasonal ones are as much ocean as tide, so they stay in the residual.
ok = hourly["depth_m"].notna()
coef = utide.solve(hourly.index[ok], hourly.loc[ok, "depth_m"].to_numpy(), lat=lat, method="ols", conf_int="linear",
                   trend=True, verbose=False)
short = [n for n, f in zip(coef["name"], coef["aux"]["frq"]) if f * 24 > 0.5]   # cycles per hour -> per day
bare = copy.deepcopy(coef)
bare["mean"], bare["slope"] = 0.0, 0.0
fit = hourly.copy()
mean_trend = (utide.reconstruct(fit.index, coef, constit=[short[0]], verbose=False).h
              - utide.reconstruct(fit.index, bare, constit=[short[0]], verbose=False).h)   # the fit's mean and trend
fit["utide_tide_m"] = utide.reconstruct(fit.index, coef, constit=short, verbose=False).h - mean_trend
fit["utide_detided_m"] = fit["depth_m"] - fit["utide_tide_m"]

# 4. Gaps of GAP_HOURS or more in the fit's span, with the de-tided level a day either side: a jump of centimetres or
#    more is most likely a recovery and redeployment (the gauge set down at another depth), not the seafloor moving.
have = fit.index[ok]
for a, b in zip(have[:-1], have[1:]):
    if b - a >= pd.Timedelta(hours=GAP_HOURS):
        before = fit.loc[a - pd.Timedelta(hours=24):a, "utide_detided_m"].mean()
        after = fit.loc[b:b + pd.Timedelta(hours=24), "utide_detided_m"].mean()
        print(f"gap {a} to {b}: de-tided depth {before:.3f} m before, {after:.3f} m after ({(after - before) * 100:+.1f} cm)")

hourly = fit[(fit.index >= start) & (fit.index < end)].copy()
if GODIN:   # A24 A24 A25: removes the daily and twice-daily tides; the first and last 35 hours are lost
    hourly["godin_m"] = (hourly["depth_m"].rolling(24, center=True).mean().rolling(24, center=True).mean()
                         .rolling(25, center=True).mean())


# 5. How much tide is left (the hourly de-tided depth's spread about its own 2-day running mean), the largest tides
#    and the trend.
def rms(x):
    return float(np.sqrt(np.nanmean((x - x.rolling(49, center=True, min_periods=25).mean()) ** 2)) * 100)


print(f"depth {hourly['depth_m'].mean():.2f} m (mean); tide left: {rms(hourly['utide_detided_m']):.2f} cm rms")
order = np.argsort(-coef["A"])[:8]
print("largest tides:", ", ".join(f"{coef['name'][i]} {coef['A'][i] * 100:.1f} cm" for i in order))
good = hourly["utide_detided_m"].notna()
if good.sum() > 48:
    days = (hourly.index[good] - hourly.index[0]).total_seconds() / 86400
    rate = np.polyfit(days, hourly.loc[good, "utide_detided_m"], 1)[0] * 365.25 * 100
    print(f"de-tided depth trend over {START} to {END}: {rate:.1f} cm/yr; over the fit's span: "
          f"{coef['slope'] * 365.25 * 100:.1f} cm/yr (a quartz gauge drifts: see the pitfalls)")

name = f"{REFDES}_{START}_{END}"
hourly.rename_axis("time_utc").to_csv(name + "_hourly.csv", float_format="%.4f")
pd.DataFrame({"constituent": coef["name"], "amplitude_m": coef["A"], "phase_deg": coef["g"],
              "amplitude_ci_m": coef["A_ci"]}).to_csv(name + "_tides.csv", index=False, float_format="%.5f")

# 6. Plot: the depth with the fitted tide; the de-tided depths (each about its own mean).
fig, (a, b) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
a.plot(hourly.index, hourly["depth_m"], "k", lw=0.5, label="depth (hourly)")
a.plot(hourly.index, hourly["depth_m"].mean() + hourly["utide_tide_m"], "c", lw=0.5, label="UTide tide")
a.invert_yaxis()
a.set_ylabel("depth (m)")
a.legend(loc="upper right")
for col, style, label in (("utide_detided_m", "k", "UTide"), ("godin_m", "tab:blue", "Godin")):
    if col in hourly:
        b.plot(hourly.index, (hourly[col] - hourly[col].mean()) * 100, style, lw=0.7, label=label)
b.invert_yaxis()
b.set_ylabel("de-tided depth change (cm)\nup is shallower")
b.legend(loc="upper right")
a.set_title(f"{REFDES} (OO.{sta}.10, EarthScope): depth from the seafloor pressure, {START} to {END}")
fig.tight_layout()
fig.savefig(name + ".png", dpi=150)
