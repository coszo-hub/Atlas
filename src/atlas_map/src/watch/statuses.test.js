import { describe, expect, it } from "vitest";
import { applyStatuses, effectiveStatus } from "./statuses.js";

const live = { instruments: { "CE04OSPS-SF01B-2A-CTDPFA107": { operational: "OFFLINE" }, "RS03CCAL-MJ03F-07-A0ABPA301": { operational: "OPERATIONAL" },
  "RS03CCAL-MJ03F-05-BOTPTA301": { operational: "FAILED" } } };

describe("each sensor's status on the map", () => {
  it("is Nereus's live status, by designator or alias", () => {
    expect(effectiveStatus({ refdes: "CE04OSPS-SF01B-2A-CTDPFA107", status: "UNKNOWN" }, live, {})).toEqual({ status: "OFFLINE", statusSource: "Nereus (live)" });
    expect(effectiveStatus({ refdes: "RS03CCAL-MJ03F-AOABPA301", aliases: ["A0ABPA301", "RS03CCAL-MJ03F-07-A0ABPA301"], status: "UNKNOWN" }, live, {}).status).toBe("OPERATIONAL");
  });
  it("is operating for a sensor Nereus does not know that the Watcher found recording", () => {
    expect(effectiveStatus({ id: "EARTHSCOPE-OO-HYS14", status: "UNKNOWN" }, live, { "EARTHSCOPE-OO-HYS14": { state: "diverted" } }).status).toBe("OPERATIONAL");
    expect(effectiveStatus({ id: "COSZO-BPR-O1", status: "UNKNOWN" }, live, {})).toBeNull();
  });
  it("is set on the bundle with its group, and goes back to the catalog's without a live answer", () => {
    const bundle = { sensors: [{ id: "B", refdes: "RS03CCAL-MJ03F-05-BOTPTA301", status: "OPERATIONAL", statusGroup: "operating", statusSource: "Nereus snapshot" }] };
    expect(applyStatuses(bundle, live, {})).toBe(true);
    expect(bundle.sensors[0]).toMatchObject({ status: "FAILED", statusGroup: "offline", statusSource: "Nereus (live)" });
    expect(applyStatuses(bundle, live, {})).toBe(false);   // nothing new
    applyStatuses(bundle, null, {});
    expect(bundle.sensors[0]).toMatchObject({ status: "OPERATIONAL", statusGroup: "operating", statusSource: "Nereus snapshot" });
  });
});
