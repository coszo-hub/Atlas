import test from "node:test";
import assert from "node:assert/strict";
import { authorYear, instrumentAsked, linkInstruction, linkPlan, linkTermsIn, listRecord, pickPaper, profileRecord } from "../src/links.js";

test("a method, concept or site is matched with the words the links were built with", () => {
  assert.deepEqual(linkTermsIn("Which papers did ambient noise interferometry using RCA data?").map((t) => t.id), ["METHOD-ambient-noise-interferometry"]);
  assert.deepEqual(linkTermsIn("papers measuring dv/v at Axial").map((t) => t.id).sort(), ["METHOD-ambient-noise-interferometry", "SITE-axial-seamount"]);
  // The narrower entry, not its parent: DAS rather than fiber sensing.
  assert.deepEqual(linkTermsIn("Which papers used distributed acoustic sensing?").map((t) => t.id), ["METHOD-das"]);
  // "RCA data" says where the data are from: it does not ask for papers on cabled observatories.
  assert.ok(!linkTermsIn("Which papers did template matching using RCA data?").some((t) => t.id === "CONCEPT-cabled-observatories"));
});

test("a first author and year are read from the question, not a month or a place", () => {
  assert.deepEqual(authorYear("What methods does Bartlow et al. (2020) on A Long-Term View of Episodic Tremor use?"),
    { surname: "Bartlow", year: 2020, hint: "A Long-Term View of Episodic Tremor use" });
  assert.equal(authorYear("what is Chadwick 2016 about").surname, "Chadwick");
  assert.equal(authorYear("Summarize Krauss and Wilcock (2025).").surname, "Krauss");
  assert.equal(authorYear("What happened at Axial in April 2015?"), null);
  assert.equal(authorYear("Which papers used OOI 2021 DAS data?"), null);
});

test("each kind of question gets its plan", () => {
  assert.equal(linkPlan("What methods does Bartlow et al. (2020) use?").kind, "profile");
  assert.equal(linkPlan("What methods have been applied to HYSB1 data?", { instrument: true }).kind, "sensor_methods");
  assert.equal(linkPlan("how have people analyzed data from AXCC1", { instrument: true }).kind, "sensor_methods");
  const topic = linkPlan("Which papers did ambient noise interferometry using RCA data?");
  assert.equal(topic.kind, "topic");
  assert.equal(topic.rca, true);
  assert.equal(linkPlan("who has applied template matching to Regional Cabled Array data").kind, "topic");
  assert.equal(linkPlan("What research has been published on shallow slow slip?").terms[0].id, "CONCEPT-shallow-slow-slip");
  assert.equal(linkPlan("Which papers are about Axial Seamount?").kind, "site");
  assert.equal(linkPlan("what research has been done at slope base").terms[0].id, "SITE-oregon-slope-base");
  // An instrument's papers stay with the instrument lookup.
  assert.equal(linkPlan("Which papers used data from HYSB1?", { instrument: true }), null);
  assert.equal(linkPlan("What is the depth of AXCC1?", { instrument: true }), null);
});

test("a site written in capitals is not an instrument", () => {
  assert.equal(instrumentAsked({ codes: ["ASHES"] }), false);
  assert.equal(instrumentAsked({ codes: ["HYSB1"] }), true);
  assert.equal(linkPlan("Which papers are about the ASHES vent field?", { instrument: instrumentAsked({ codes: ["ASHES"] }) }).kind, "site");
});

test("the paper meant is the one whose title the question starts", () => {
  const papers = [{ paper_id: "A", title: "Geodetic monitoring at Axial" }, { paper_id: "B", title: "A Long-Term View of Episodic Tremor and Slip" }];
  assert.deepEqual(pickPaper(papers, "A Long-Term View of Episodic").map((p) => p.paper_id), ["B"]);
  assert.deepEqual(pickPaper(papers, "").map((p) => p.paper_id), ["A", "B"]);
});

test("a paper's links become one record; a list record says what RCA data the paper used", () => {
  const hit = (predicate, target, text) => ({ chunk_id: target, title: "T", text, citations: [],
    metadata: { node_local_id: "P1", link: { predicate, target_name: target, sensors_used: ["EARTHSCOPE-OO-HYSB1"], methods: ["Ambient noise interferometry"] } } });
  const record = profileRecord({ paper_id: "P1", title: "Active protothrusts", publication_year: 2026, citation: "Kidiwela" },
    [hit("STUDIES_CONCEPT", "Shallow slow slip", "T (2026) studies Shallow slow slip: named in its abstract. Evidence: x"),
     hit("APPLIES_METHOD", "Ambient noise interferometry", "T (2026) applies the method Ambient noise interferometry: y")]);
  assert.match(record.text, /^Literature links of Active protothrusts \(2026\)/);
  assert.ok(record.text.indexOf("Applies the method") < record.text.indexOf("Studies"));
  assert.match(listRecord(hit("APPLIES_METHOD", "M", "z")).text, /used data from RCA sensors: EARTHSCOPE-OO-HYSB1/);
  assert.match(listRecord(hit("USES_SENSOR", "S", "z"), { withMethods: true }).text, /Methods this paper applies \(its links\): Ambient noise interferometry/);
  assert.match(linkInstruction(linkPlan("Which papers did ambient noise interferometry using RCA data?")), /with RCA or OOI data/);
});
