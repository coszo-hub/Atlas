import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HudDock from "../ui/HudDock.jsx";
import { WatchProvider } from "./WatchProvider.jsx";
import { WatchLine, reportSpan } from "./WatchPanel.jsx";

const REPORT = { day: "2026-11-15", axial200Hz: "Navy Diversion", sensors: [
  { id: "HYS14", refdes: null, state: "diverted", since: "2026-11-15", source: "EarthScope", method: "earthscope", gap: 10 },
  { id: "POD", refdes: "CE04OSPS-SF01B-2A-CTDPFA107", state: "no_data", since: "2026-08-03", source: "OOI ERDDAP", method: "erddap", gap: 360, nereusStatus: "OFFLINE" },
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
    expect(key).toHaveTextContent("Watcher · Nov 15, 2026 UTC");
    expect(key).toHaveTextContent(/Not recording\s*1/);
    expect(key).toHaveTextContent(/Navy diversion\s*1/);
    expect(key).toHaveTextContent(/Gaps\s*1/);
    expect(key).toHaveTextContent("4 sensors watched");
    expect(key).toHaveTextContent("200 Hz data under Navy diversion");
  });
  it("a colour's row lists its sensors, and a sensor in the list opens its card", async () => {
    mockFetch();
    const onSensor = vi.fn();
    const bundle = { sensorById: { POD: { name: "Oregon Offshore Cabled Shallow Profiler Mooring CTD", site: "osps" } }, siteById: { osps: { label: "Oregon Offshore Cabled Shallow Profiler Mooring" } } };
    await mount(<HudDock scene={{ U: { exag: { value: 6 } } }} credit="GMRT" bundle={bundle} onSensor={onSensor} />);
    fireEvent.click(screen.getByRole("button", { name: /Watcher/ }));
    const row = screen.getByRole("button", { name: /Not recording\s*1/ });
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
  it("a sensor's card says its state, since when, Nereus's word and the check", async () => {
    mockFetch();
    await mount(<WatchLine id="POD" />);
    expect(screen.getByText(/Not recording since Aug 3, 2026 · Nereus: offline/)).toBeInTheDocument();
    expect(screen.getByText(/checked by OOI ERDDAP/)).toBeInTheDocument();
  });
  it("shows nothing for a sensor the Watcher does not watch", async () => {
    mockFetch();
    await mount(<WatchLine id="COSZO-BPR-O1" />);
    expect(screen.queryByText("Watcher")).toBeNull();
  });
});
