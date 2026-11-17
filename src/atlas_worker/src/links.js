// The literature links (src/literature_links/build_literature_links.py): which question asks for which links, and
// how to read them. The methods, concepts and sites are matched with the same words the links were built with
// (link_terms.json, written by the builder), so "ambient noise interferometry", "dv/v" and "noise cross-correlation"
// all reach the one method.
import LINK_TERMS from "./link_terms.json" with { type: "json" };

const TERMS = LINK_TERMS.map((term) => ({ ...term, rx: new RegExp(term.pattern, term.flags) }));
// The RCA's own names say where the data are from, not what the question is about ("using RCA data").
const SCOPE = /\b(?:RCA|OOI|Regional Cabled Array|Ocean Observatories Initiative|cabled array|cabled observatory)\b/gi;
export const asksRcaData = (question) => new RegExp(SCOPE.source, "i").test(String(question || ""));

// The methods, concepts and sites a question names, the most specific of each line ("DAS" rather than "fiber sensing").
export function linkTermsIn(question) {
  const q = String(question || "");
  const unscoped = q.replace(SCOPE, " ");
  const found = TERMS.filter((term) => term.rx.test(term.kind === "site" ? q : unscoped));
  const ids = new Set(found.map((term) => term.id));
  return found.filter((term) => !TERMS.some((child) => child.parent === term.id && ids.has(child.id)))
    .map(({ id, kind, name }) => ({ id, kind, name }));
}

// "Chadwick et al. (2012)", "Kidiwela 2026", "Krauss and Wilcock (2025)": a first author's surname and a year.
const NOT_SURNAMES = new Set(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December", "Axial", "Seamount", "Since", "From", "During", "Between", "After", "Before", "Until", "Through", "In",
  "The", "Summer", "Winter", "Spring", "Fall", "Autumn", "Eruption", "OOI", "RCA", "COSZO", "Cascadia", "Oregon", "What", "Which"]);
export function authorYear(question) {
  const rx = /\b([A-Z][\p{L}'’-]+)(?:\s+(?:et\s+al\.?|and\s+[A-Z][\p{L}'’-]+|&\s+[A-Z][\p{L}'’-]+))?\s*,?\s*\(?((?:19|20)\d\d)\)?/gu;
  for (const m of String(question || "").matchAll(rx)) {
    if (!NOT_SURNAMES.has(m[1]) && !/^[A-Z0-9]+$/.test(m[1])) {
      // "on A Long-Term View of …": the title's first words, when the question gives them.
      const hint = String(question).slice(m.index + m[0].length).match(/^\s*on\s+([^?.]+)/)?.[1]?.trim() || "";
      return { surname: m[1], year: Number(m[2]), hint };
    }
  }
  return null;
}

const ASKS_PAPERS = /\b(?:which|what|list|any|find|show|name)\s+(?:[\w-]+\s+){0,2}(?:papers?|studies|publications?|articles?|research)\b|\b(?:papers?|studies|publications?|articles?)\s+(?:that|which|have|has|about|on)\b|^\s*(?:papers?|publications?|studies)\b|\bwho\s+(?:has|have)\b|\bresearch\s+(?:has|have)\s+been\b/i;
const METHOD_ASK = /\b(?:methods?|techniques?|approach(?:es)?|analy[sz](?:e|es|ed|is|ing)|tools?)\b/i;

// What a question asks of the links:
// - profile: a paper's methods, concepts, sites and sensors ("What methods does Bartlow et al. (2020) use?");
// - sensor_methods: the methods applied to an instrument's data (the papers that used it, with their methods);
// - topic: the papers that applied a method or studied a concept (rca: with RCA data);
// - site: the papers about a site.
// An instrument's papers ("which papers used HYSB1") stay with papersFor; null when none of these.
export function linkPlan(question, { instrument = false } = {}) {
  const q = String(question || "");
  const paper = authorYear(q);
  if (paper) return { kind: "profile", ...paper };
  const terms = linkTermsIn(q);
  const topics = terms.filter((term) => term.kind !== "site");
  const sites = terms.filter((term) => term.kind === "site");
  if (instrument && METHOD_ASK.test(q) && !topics.length) return { kind: "sensor_methods" };
  if (!ASKS_PAPERS.test(q)) return null;
  if (topics.length && !(instrument && !topics.some((term) => term.kind === "method"))) {
    return { kind: "topic", terms: topics, sites, rca: asksRcaData(q) };
  }
  if (sites.length && !instrument) return { kind: "site", terms: sites };
  return null;
}

// The papers the author lookup found that the question means: the one whose title starts with the question's hint,
// else (two papers by that author that year) both.
export function pickPaper(papers, hint = "") {
  const words = (text) => String(text || "").toLowerCase().replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  const want = words(hint).slice(0, 5);
  if (want.length) {
    const match = papers.find((p) => want.every((w, i) => words(p.title)[i] === w));
    if (match) return [match];
  }
  return papers.slice(0, 2);
}

const RELATION = { USES_SENSOR: "used data from", MENTIONS_SENSOR: "mentions", APPLIES_METHOD: "applies the method",
  STUDIES_CONCEPT: "studies", ABOUT_SITE: "is about", NAMES_FEATURE: "names" };
// One record for a paper's own links, in order: methods, concepts, sites, sensors used, sensors mentioned.
export function profileRecord(paper, hits) {
  const order = ["APPLIES_METHOD", "STUDIES_CONCEPT", "ABOUT_SITE", "USES_SENSOR", "MENTIONS_SENSOR"];
  const mine = hits.filter((hit) => hit.metadata?.node_local_id === paper.paper_id && order.includes(hit.metadata?.link?.predicate));
  if (!mine.length) return null;
  const lines = [];
  for (const predicate of order) {
    const rows = mine.filter((hit) => hit.metadata.link.predicate === predicate);
    if (!rows.length) continue;
    lines.push(`${RELATION[predicate][0].toUpperCase()}${RELATION[predicate].slice(1)}:`);
    for (const hit of rows) {
      const quote = String(hit.text || "").replace(/^.*?:\s*/, "").slice(0, 320);
      lines.push(`- ${hit.metadata.link.target_name}: ${quote}`);
    }
  }
  const first = mine[0];
  return { ...first, chunk_id: `LINKS-${paper.paper_id}`, title: paper.title,
    text: `Literature links of ${paper.title} (${paper.publication_year}), ${paper.citation || ""}\n${lines.join("\n")}`,
    layer: true, paperList: true };
}

// A link record as a line of a paper list: the link's own text, and what the paper used (for "with RCA data").
export function listRecord(hit, { withMethods = false } = {}) {
  const link = hit.metadata?.link || {};
  const used = (link.sensors_used || []).length ? ` It used data from RCA sensors: ${link.sensors_used.slice(0, 6).join(", ")}.` : "";
  const methods = withMethods && (link.methods || []).length ? ` Methods this paper applies (its links): ${link.methods.join("; ")}.` : "";
  return { ...hit, text: `${String(hit.text || "").slice(0, 700)}${used}${methods}`, layer: true, paperList: true };
}

// What the answer is told to do with the links.
export function linkInstruction(plan) {
  if (!plan) return "";
  const judged = "The links were made by rule from each paper's own words (its title, abstract or full text), so read each record's quote:";
  if (plan.kind === "profile") {
    return `The evidence holds the literature links of the paper asked about, under 'Literature links of': the methods it applies, the concepts and features it studies, the sites it is about and the RCA sensors it used or mentions, each with how it was found and a quote. ${judged} answer from those that the quote supports, citing the paper (for a methods question, the methods; for what it studies, the concepts and features), and leave out a link whose quote shows the paper only mentions it.`;
  }
  if (plan.kind === "sensor_methods") {
    return `The question asks which methods have been applied to an instrument's data. Each literature-link record of a paper that used the instrument's data ends with the methods that paper applies. Answer with the methods, each with the papers that applied it to this instrument's data (title and citation); a paper that only mentions the instrument does not count. ${judged} a paper whose quote does not show it used the data does not count.`;
  }
  if (plan.kind === "topic") {
    const names = plan.terms.map((term) => term.name).join(", ");
    const method = plan.terms.some((term) => term.kind === "method");
    const verb = method ? "applied" : "studied";
    return `The question asks which papers ${verb} ${names}${plan.rca ? " with RCA or OOI data" : ""}. Literature-link records in the evidence each say a paper ${method ? "applies the method" : "studies"} it and how that was found${plan.rca ? ", and which RCA sensors' data the paper used" : ""}. ${judged} list under 'Papers that ${method ? "applied it" : "studied it"}' every paper whose record shows it ${verb} ${names}${plan.rca ? " (with the RCA data the record names)" : ""}, by title with its citation and a few words on what it did. A paper whose quote shows it only mentions or cites it goes under 'Papers that mention it'. Give every paper that qualifies, not the first few, and only scientific papers.`;
  }
  return `The question asks which papers are about ${plan.terms.map((term) => term.name).join(", ")}. Literature-link records in the evidence each say a paper is about the site (its title or abstract names it, or the RCA sensors whose data it used are there). List every one of those papers by title with its citation and a few words on its subject; give every paper, not the first few, and only scientific papers.`;
}
