import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HudDock from "../ui/HudDock.jsx";
import { WatchProvider } from "./WatchProvider.jsx";
import { reportSpan } from "./WatchPanel.jsx";
import SensorStatus from "./SensorStatus.jsx";

const REPORT = { day: "2026-11-15", generatedAt: "2026-11-16T01:20:00Z", axial200Hz: "Navy Diversion", sensors: [
  { id: "HYS14", refdes: null, state: "diverted", since: "2026-11-15", source: "EarthScope", method: "earthscope", gap: 10 },
  { id: "POD", refdes: "CE04OSPS-SF01B-2A-CTDPFA107", state: "no_data", since: "2026-08-03", source: "OOI ERDDAP", method: "erddap", gap: 360, nereusStatus: "OFFLINE" },
  { id: "BOTPT", refdes: "RS03CCAL-MJ03F-05-BOTPTA301", state: "no_data", since: "2026-10-28", lastData: "2026-10-28T22:38:00Z", source: "OOI ERDDAP", method: "erddap", gap: 30,
    nereusStatus: "FAILED", note: { title: "Data output stopped - again", message: "No data output or ping response. Instrument set to failed.", startedAt: "2026-10-28T22:39:00+00:00" } },
  { id: "HYDBB", refdes: "RS01SLBS-LJ01A-09-HYDBBA102", state: "gaps", since: "2026-11-15", source: "Nereus (data check)", method: "nereus", gap: 30 },
  { id: "CTD", refdes: "RS01SLBS-LJ01A-12-CTDPFB101", state: "ok", since: "2026-11-15", source: "Nereus (data check)", method: "nereus", gap: 60 },
] };
const LIVE = { fetchedAt: "2026-11-16T18:30:00Z", instruments: {} };

function mockFetch() {
  vi.stubGlobal("fetch", vi.fn(async url => ({ ok: true, json: async () => (String(url).includes("latest.json") ? REPORT : LIVE) })));
}
const mount = async ui => { await act(async () => { render(<WatchProvider>{ui}</WatchProvider>); }); };

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe("the Watcher", () => {
  it("names a report's span: the 24 hours to when it ran, or a re-graded UTC day", () => {
    expect(reportSpan({ day: "2026-11-17", from: "2026-11-16T01:20:00Z", to: "2026-11-17T01:20:00Z" })).toBe("24 h to Nov 17, 01:20 UTC");
    expect(reportSpan({ day: "2026-11-15", from: "2026-11-15T00:00:00Z", to: "2026-11-16T00:00:00Z" })).toBe("Nov 15, 2026 UTC");
    expect(reportSpan({ day: "2026-11-15" })).toBe("Nov 15, 2026 UTC");
  });
  it("the owl button turns the Watcher view on, with its key and counts", async () => {
    mockFetch();
    await mount(<HudDock scene={{ U: { exag: { value: 6 } } }} credit="GMRT" />);
    const owl = screen.getByRole("button", { name: /Watcher/ });
    expect(owl).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("group", { name: "Watcher" })).toBeNull();
    fireEvent.click(owl);
    expect(owl).toHaveAttribute("aria-pressed", "true");
    const key = screen.getByRole("group", { name: "Watcher" });
    expect(key).toHaveTextContent("Watcher · daily check Nov 15, 2026 UTC");
    expect(key).toHaveTextContent(/Not recording\s*2/);
    expect(key).toHaveTextContent(/Navy diversion\s*1/);
    expect(key).toHaveTextContent(/Gaps\s*1/);
    expect(key).toHaveTextContent("5 sensors watched");
    expect(key).toHaveTextContent("200 Hz data under Navy diversion");
  });
  it("a colour's row lists its sensors, and a sensor in the list opens its card", async () => {
    mockFetch();
    const onSensor = vi.fn();
    const bundle = { sensorById: { POD: { name: "Oregon Offshore Cabled Shallow Profiler Mooring CTD", site: "osps" } }, siteById: { osps: { label: "Oregon Offshore Cabled Shallow Profiler Mooring" } } };
    await mount(<HudDock scene={{ U: { exag: { value: 6 } } }} credit="GMRT" bundle={bundle} onSensor={onSensor} />);
    fireEvent.click(screen.getByRole("button", { name: /Watcher/ }));
    const row = screen.getByRole("button", { name: /Not recording\s*2/ });
    expect(row).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Not recording: sensors" });
    expect(list).toHaveTextContent("CTD");   // its site is on the line below
    expect(list).toHaveTextContent("Oregon Offshore Cabled Shallow Profiler Mooring");
    expect(list).toHaveTextContent("since Aug 3, 2026");
    fireEvent.click(screen.getByRole("button", { name: /^CTD/ }));
    expect(onSensor).toHaveBeenCalledWith("POD");
  });
  it("a card's status: a sentence, the operators' note, and where it comes from", async () => {
    mockFetch();
    await mount(<SensorStatus sensor={{ id: "BOTPT", refdes: "RS03CCAL-MJ03F-05-BOTPTA301", access: [] }} />);
    expect(screen.getByText("Not recording").closest("p")).toHaveTextContent("Not recording: no data since Oct 28, 2026, 22:38 UTC.");
    expect(screen.getByText(/Operators' note, Oct 28, 2026: Data output stopped - again · Nereus lists it as failed/)).toBeInTheDocument();
    expect(screen.getByText("No data output or ping response. Instrument set to failed.")).toBeInTheDocument();
    expect(screen.getByText("Daily check: Nov 16, 2026, 01:20 UTC (the 24 h before) · from OOI ERDDAP")).toBeInTheDocument();
  });
  it("without a note, Nereus's word in a sentence", async () => {
    mockFetch();
    await mount(<SensorStatus sensor={{ id: "POD", refdes: "CE04OSPS-SF01B-2A-CTDPFA107", access: [] }} />);
    expect(screen.getByText("Nereus, the RCA's instrument monitor, lists it as offline.")).toBeInTheDocument();
  });
  it("a sensor the Watcher does not grade shows the live status line instead", async () => {
    mockFetch();
    await mount(<SensorStatus sensor={{ id: "COSZO-BPR-O1", refdes: null, status: "UNKNOWN", access: [] }} />);
    expect(screen.queryByText(/Not recording|Recording/)).toBeNull();
    expect(screen.getByText(/Status unknown/)).toBeInTheDocument();
  });
});

describe("which check a status is from", () => {
  it("the daily check, with when it ran; or Nereus's live check, with when, and what the daily check said", async () => {
    const { checkedLine } = await import("./SensorStatus.jsx");
    const report = { generatedAt: "2026-11-16T01:20:00Z", day: "2026-11-16" };
    expect(checkedLine({ day: true, source: "OOI ERDDAP" }, report)).toBe("Daily check: Nov 16, 2026, 01:20 UTC (the 24 h before) · from OOI ERDDAP");
    expect(checkedLine({ day: false, liveAt: "2026-11-16T21:30:00Z", dailyState: "ok" }, report))
      .toBe("Checked live: Nov 16, 2026, 21:30 UTC · by Nereus (daily check, Nov 16, 2026, 01:20 UTC: Recording normally)");
  });
});
