import { describe, expect, it } from "vitest";
import { watchBeams } from "./WatchLayer.js";

describe("the Watcher's beams", () => {
  const sites = [{ id: "ccal", sensorIds: ["botpt", "axcc1", "ctd", "hydlf"] }, { id: "slbs", sensorIds: ["ctd2"] }, { id: "shr", sensorIds: ["a", "b"] }];
  const states = { botpt: { state: "no_data" }, axcc1: { state: "diverted" }, hydlf: { state: "diverted" }, ctd: { state: "ok" },
    ctd2: { state: "unchecked" }, a: { state: "gaps" }, b: { state: "gaps" } };
  const beams = watchBeams(sites, states);
  it("gives a site one beam per problem among its sensors, worst first, side by side", () => {
    expect(beams.filter(b => b.site.id === "ccal").map(b => [b.state, b.ids, b.k, b.of]))
      .toEqual([["no_data", ["botpt"], 0, 2], ["diverted", ["axcc1", "hydlf"], 1, 2]]);
  });
  it("counts a state's sensors in one beam, and gives a site without a problem none", () => {
    expect(beams.filter(b => b.site.id === "shr").map(b => [b.state, b.ids.length])).toEqual([["gaps", 2]]);
    expect(beams.some(b => b.site.id === "slbs")).toBe(false);
  });
});
