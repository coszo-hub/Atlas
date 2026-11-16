"""python -m unittest discover -s src/atlas_watch"""
import struct
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_watchlist   # noqa: E402
import check   # noqa: E402

DAY = datetime(2026, 11, 15, tzinfo=timezone.utc).timestamp()


def record(start: datetime, nsamp: int, factor: int, mult: int, length_exp: int = 9) -> bytes:
    """A MiniSEED 2 record: fixed header, then blockette 1000 at 48 giving the record length."""
    head = bytearray(48)
    head[20:30] = struct.pack(">HHBBBBH", start.year, start.timetuple().tm_yday, start.hour, start.minute, start.second, 0, 0)
    head[30:36] = struct.pack(">Hhh", nsamp, factor, mult)
    head[46:48] = struct.pack(">H", 48)
    b1000 = struct.pack(">HHBBBB", 1000, 0, 11, 1, length_exp, 0)
    raw = bytes(head) + b1000
    return raw + bytes(2 ** length_exp - len(raw))


class GapTests(unittest.TestCase):
    def test_coverage_and_longest_gap(self):
        spans = [(DAY, DAY + 3600), (DAY + 7200, DAY + 86400)]
        coverage, longest, last = check.spans_gaps(spans, DAY, DAY + 86400)
        self.assertAlmostEqual(coverage, 23 / 24)
        self.assertEqual(longest, 60)
        self.assertEqual(last, DAY + 86400)

    def test_a_day_that_stops_early_ends_in_a_gap(self):
        coverage, longest, _ = check.spans_gaps([(DAY, DAY + 43200)], DAY, DAY + 86400)
        self.assertEqual((coverage, longest), (0.5, 720))
        self.assertEqual(check.grade(coverage, longest, 60), "gaps")
        self.assertEqual(check.grade(0, 1440, 60), "no_data")
        self.assertEqual(check.grade(1, 5, 10), "ok")

    def test_miniseed_records_give_their_spans(self):
        t = datetime(2026, 11, 15, 1, 2, 3, tzinfo=timezone.utc)
        raw = record(t, 800, 8, 1) + record(t.replace(minute=5), 400, 8, 1, length_exp=12)
        spans = check.mseed_spans(raw)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0], (t.timestamp(), t.timestamp() + 100))
        self.assertEqual(spans[1][1] - spans[1][0], 50)


class NereusTests(unittest.TestCase):
    def hours(self, codes):
        return [{"date": f"2026-11-15T{h:02d}:00:00+00:00", "code": c} for h, c in enumerate(codes)]

    def grade(self, codes, gap=30, back=()):
        sensor = {"check": {"refdes": "R"}, "gap": gap}
        calls = iter([self.hours(codes), list(back)])
        with mock.patch.object(check, "nereus_history", lambda *a: next(calls)):
            return check.check_nereus(sensor, date(2026, 11, 15), {"R": {"id": 1}})

    def test_bad_hours_longer_than_the_normal_gap_are_gaps(self):
        r = self.grade(["GOOD"] * 11 + ["BAD"] * 13)
        self.assertEqual((r["state"], r["longestGapMin"], r["lastData"]), ("gaps", 780, "2026-11-15T11:00:00Z"))
        self.assertEqual(self.grade(["GOOD"] * 23 + ["BAD"], gap=60)["state"], "ok")

    def test_a_day_without_a_good_hour_is_no_data_since_the_last_one(self):
        back = [{"date": "2026-11-02T06:00:00+00:00", "code": "GOOD"}, {"date": "2026-11-02T07:00:00+00:00", "code": "BAD"}]
        r = self.grade(["BAD"] * 24, back=back)
        self.assertEqual((r["state"], r["lastData"]), ("no_data", "2026-11-02T07:00:00Z"))

    def test_unmonitored_is_unchecked(self):
        self.assertEqual(self.grade(["UNMONITORED"] * 24)["state"], "unchecked")


class WatchlistTests(unittest.TestCase):
    nereus = {"RS01SLBS-LJ01A-12-CTDPFB101": {"operationalStatusCode": "OPERATIONAL", "dataCheckIsEnabled": True,
                                              "latestDataStatusConnection": {"status": {"code": "GOOD"}}},
              "CE04OSPD-DP01B-01-CTDPFL105": {"operationalStatusCode": "NOT_DEPLOYED"},
              "CE04OSPS-SF01B-2A-CTDPFA107": {"operationalStatusCode": "OFFLINE",
                                              "latestDataStatusConnection": {"status": {"code": "UNMONITORED"}}}}

    def sensor(self, refdes, status="UNKNOWN", **extra):
        return {"id": refdes, "refdes": refdes, "status": status, "access": [], **extra}

    def test_nereus_status_decides_who_is_watched(self):
        self.assertTrue(build_watchlist.watched(self.sensor("RS01SLBS-LJ01A-12-CTDPFB101"), self.nereus))
        self.assertFalse(build_watchlist.watched(self.sensor("CE04OSPD-DP01B-01-CTDPFL105", "OPERATIONAL"), self.nereus))
        self.assertTrue(build_watchlist.watched(self.sensor("CE04OSPS-SF01B-2A-CTDPFA107"), self.nereus))   # offline: red
        self.assertFalse(build_watchlist.watched(self.sensor("RS01SUM2-MJ01B-BOTPTA301"), self.nereus))   # no port: reference only
        self.assertFalse(build_watchlist.watched(self.sensor("COSZO-BPR-O1"), self.nereus))
        self.assertTrue(build_watchlist.watched({"id": "EARTHSCOPE-OO-HYS14", "access": []}, self.nereus))

    def test_check_order(self):
        hydlf = self.sensor("RS01SLBS-MJ01A-05-HYDLFA101", access=[{"kind": "earthscope", "station": "HYSB1", "channel": "HDH"}])
        self.assertEqual(build_watchlist.check_of(hydlf, self.nereus, set())["channel"], "HDH")
        ctd = self.sensor("RS01SLBS-LJ01A-12-CTDPFB101", access=[{"kind": "erddap", "datasetId": "ooi-rs01slbs-lj01a-12-ctdpfb101"}])
        self.assertEqual(build_watchlist.check_of(ctd, self.nereus, {"ooi-rs01slbs-lj01a-12-ctdpfb101"})["method"], "nereus")
        pod = self.sensor("CE04OSPS-SF01B-2A-CTDPFA107")
        self.assertEqual(build_watchlist.check_of(pod, self.nereus, {"ooi-ce04osps-sf01b-2a-ctdpfa107"}),
                         {"method": "erddap", "dataset": "ooi-ce04osps-sf01b-2a-ctdpfa107"})
        self.assertEqual(build_watchlist.check_of(self.sensor("RS03INT1-MJ03C-07-RASFLA301"), self.nereus, set()), {"method": "none"})


if __name__ == "__main__":
    unittest.main()


class CombinedTests(unittest.TestCase):
    day = date(2026, 11, 15)

    def test_erddap_data_outweigh_a_bad_nereus_day(self):
        r = check.combined({"state": "no_data", "source": "Nereus"}, {"state": "ok", "coverage": 1.0, "lastData": "2026-11-15T23:50:00Z",
                                                                       "erddapNewest": "2026-11-16T03:00:00Z"}, self.day)
        self.assertEqual((r["state"], r["agree"]), ("ok", False))

    def test_an_erddap_gap_makes_a_good_nereus_day_yellow(self):
        r = check.combined({"state": "ok"}, {"state": "gaps", "longestGapMin": 120, "erddapNewest": "2026-11-16T03:00:00Z"}, self.day)
        self.assertEqual(r["state"], "gaps")

    def test_erddap_behind_the_day_says_nothing(self):
        behind = {"state": "no_data", "coverage": 0.0, "erddapNewest": "2026-11-14T11:30:00Z"}
        self.assertEqual(check.combined({"state": "ok"}, behind, self.day)["state"], "ok")
        passed = {**behind, "erddapNewest": "2026-11-16T01:00:00Z"}
        self.assertEqual(check.combined({"state": "ok"}, passed, self.day)["state"], "gaps")

    def test_an_unmonitored_nereus_day_takes_erddap(self):
        r = check.combined({"state": "unchecked"}, {"state": "ok", "source": "OOI ERDDAP"}, self.day)
        self.assertEqual((r["state"], r["source"]), ("ok", "OOI ERDDAP"))
