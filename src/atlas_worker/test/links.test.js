import test from "node:test";
import assert from "node:assert/strict";
import { authorYear, instrumentAsked, linkAppendix, linkInstruction, recentPapers, withoutNamedTerms, linkPlan, linkTermsIn, listRecord, pickPaper, profileRecord } from "../src/links.js";

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
  assert.equal(linkPlan("tell me about southern hydrate ridge").kind, "site_overview");
  assert.equal(linkPlan("What is the depth at Southern Hydrate Ridge?"), null);
  assert.equal(linkPlan("what research has been done at slope base").terms[0].id, "SITE-oregon-slope-base");
  // An instrument's papers stay with the instrument lookup.
  assert.equal(linkPlan("Which papers used data from HYSB1?", { instrument: true }).kind, "sensor_papers");
  assert.equal(linkPlan("What is the depth of AXCC1?", { instrument: true }), null);
  // The instrument's own words are not a method asked about.
  assert.equal(linkPlan("Which papers used data from the Hydrate Ridge flank tidal pressure gauge?", { instrument: true }).kind, "sensor_papers");
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

test("a long list keeps its most recent papers, and the list after the answer says how many are left out", () => {
  const hit = (id, year, predicate = "ABOUT_SITE", target = "Axial Seamount") => ({ chunk_id: `L${id}`, collection_id: "literature_links",
    title: `Paper ${id}`, citations: [{ url: `https://doi.org/10.1/${id}` }],
    metadata: { node_local_id: `P${id}`, link: { predicate, target_name: target, publication_year: year } } });
  const hits = Array.from({ length: 40 }, (_, i) => hit(i, 1990 + i));
  const { shown, total, older, olderYears } = recentPapers(hits);
  assert.equal(shown.length, 30);
  assert.equal(shown[0].metadata.link.publication_year, 2029);
  assert.deepEqual([total, older, olderYears], [40, 10, [1990, 1999]]);
  const site = linkAppendix({ kind: "site", terms: [{ id: "SITE-axial-seamount", kind: "site", name: "Axial Seamount" }] }, hits);
  assert.match(site, /The 30 most recent of the 40 papers the links give about Axial Seamount/);
  assert.match(site, /10 older papers \(1990–1999\)/);
  assert.match(site, /- Paper 39 \(2029\) https:\/\/doi\.org\/10\.1\/39/);
  const sensor = linkAppendix({ kind: "sensor_papers" }, [hit(1, 2021, "USES_SENSOR", "HYSB1"), hit(2, 2018, "MENTIONS_SENSOR", "HYSB1")]);
  assert.match(sensor, /used its data \(1\)\*\*\n- Paper 1 \(2021\)/);
  assert.match(sensor, /only mention it \(1\)\*\*\n- Paper 2 \(2018\)/);
  assert.equal(linkAppendix(null, hits), "");
});

test("a method named by its own name is found, and its words are not an instrument", () => {
  assert.deepEqual(linkTermsIn("who has applied earthquake source parameters to Regional Cabled Array data").map((t) => t.id), ["METHOD-source-parameters"]);
  assert.equal(withoutNamedTerms("who has applied seafloor pressure geodesy to RCA data").includes("pressure"), false);
  assert.equal(withoutNamedTerms("List the studies that used fiber-optic sensing on OOI data.").includes("fiber"), false);
  // Only a method's name is taken out: an instrument described in a method's words stays.
  assert.match(withoutNamedTerms("Which papers used data from the tidal pressure gauge?"), /tidal pressure gauge/);
});
