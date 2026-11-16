import { describe, expect, it } from "vitest";
import { currentState, siteProblem, watchCounts, watchStates } from "./watch.js";

const NOW = Date.parse("2026-11-16T19:00:00Z");
const row = (over = {}) => ({ id: "S", refdes: "RS01SLBS-LJ01A-12-CTDPFB101", state: "ok", since: "2026-11-15", gap: 60, source: "Nereus (data check)", ...over });
const live = (check, delayMin, extra = {}) => ({ instruments: { "RS01SLBS-LJ01A-12-CTDPFB101": { check, delayMin, checkedAt: "2026-11-16T18:30:00Z", ...extra } } });

describe("the Watcher's state now: the day's report, with Nereus's live check laid over it", () => {
  it("keeps the report's state while Nereus agrees", () => {
    expect(currentState(row(), live("GOOD", 7), NOW)).toMatchObject({ state: "ok", day: true });
    expect(currentState(row({ state: "gaps" }), null, NOW).state).toBe("gaps");
  });
  it("turns a sensor that stopped since the report red, from when it stopped", () => {
    expect(currentState(row(), live("BAD", 2 * 1440), NOW)).toMatchObject({ state: "no_data", since: "2026-11-14", day: false });
  });
  it("turns one behind by more than its normal gap yellow", () => {
    expect(currentState(row(), live("BAD", 300), NOW)).toMatchObject({ state: "gaps", day: false });
    expect(currentState(row(), live("BAD", 30), NOW).state).toBe("ok");
  });
  it("shows a red day Nereus graded as recording again once Nereus is good", () => {
    expect(currentState(row({ state: "no_data" }), live("GOOD", 5), NOW)).toMatchObject({ state: "ok", day: false });
    // a red ERDDAP-checked sensor is not cleared by Nereus
    expect(currentState(row({ state: "no_data", source: "OOI ERDDAP" }), live("GOOD", 5), NOW).state).toBe("no_data");
  });
  it("leaves the Navy diversion and an unmonitored instrument to the report", () => {
    expect(currentState(row({ state: "diverted" }), live("BAD", 5000), NOW).state).toBe("diverted");
    expect(currentState(row(), live("UNMONITORED", null), NOW).state).toBe("ok");
  });
});

describe("sites and counts", () => {
  const states = watchStates({ sensors: [row({ id: "a" }), row({ id: "b", state: "gaps", refdes: null }), row({ id: "c", state: "diverted", refdes: null }),
    row({ id: "d", state: "no_data", refdes: null }), row({ id: "e", state: "unchecked", refdes: null })] }, null, NOW);
  it("a site takes its worst problem; a site with none is not highlighted", () => {
    expect(siteProblem({ sensorIds: ["a", "b", "c"] }, states)).toBe("diverted");
    expect(siteProblem({ sensorIds: ["a", "b"] }, states)).toBe("gaps");
    expect(siteProblem({ sensorIds: ["a", "d", "c"] }, states)).toBe("no_data");
    expect(siteProblem({ sensorIds: ["a", "e", "x"] }, states)).toBe(null);
  });
  it("counts the sensors recording (normal, gaps or diverted) and each problem", () => {
    expect(watchCounts(states)).toEqual({ recording: 3, no_data: 1, diverted: 1, gaps: 1, watched: 5 });
  });
});
