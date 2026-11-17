// The literature links (src/literature_links/build_literature_links.py): which question asks for which links, and
// how to read them. The methods, concepts and sites are matched with the same words the links were built with
// (link_terms.json, written by the builder), so "ambient noise interferometry", "dv/v" and "noise cross-correlation"
// all reach the one method.
import LINK_TERMS from "./link_terms.json" with { type: "json" };

// A term is also found by its own name ("earthquake source parameters", "fiber-optic sensing"), with or without
// what its name puts in brackets, not only by the words papers use for it ("stress drop", "corner frequency").
const words = (text) => String(text || "").toLowerCase().replace(/[^\p{L}\p{N}/]+/gu, " ").trim();
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
const TERMS = LINK_TERMS.map((term) => {
  const names = [...new Set([term.name, term.name.replace(/\s*\([^)]*\)/g, "")].map(words).filter((n) => n.length >= 4))];
  return { ...term, rx: new RegExp(term.pattern, term.flags),
    nameRx: names.length ? new RegExp(`(?:^| )(?:${names.map(escape).join("|")})(?: |$)`) : null };
});
// The RCA's own names say where the data are from, not what the question is about ("using RCA data").
const SCOPE = /\b(?:RCA|OOI|Regional Cabled Array|Ocean Observatories Initiative|cabled array|cabled observatory)\b/gi;
export const asksRcaData = (question) => new RegExp(SCOPE.source, "i").test(String(question || ""));
const matches = (term, text) => term.rx.test(text) || Boolean(term.nameRx?.test(words(text)));

// The methods, concepts and sites a question names, the most specific of each line ("DAS" rather than "fiber sensing").
export function linkTermsIn(question) {
  const q = String(question || "");
  const sites = TERMS.filter((term) => term.kind === "site" && matches(term, q));
  // A site's name is not a topic: "Hydrate Ridge" is not a question about gas hydrates.
  let unscoped = q.replace(SCOPE, " ");
  for (const site of sites) unscoped = unscoped.replace(new RegExp(site.rx.source, `${site.rx.flags}g`), " ");
  const found = [...sites, ...TERMS.filter((term) => !["site", "feature"].includes(term.kind) && matches(term, unscoped))];
  const ids = new Set(found.map((term) => term.id));
  return found.filter((term) => !TERMS.some((child) => child.parent === term.id && ids.has(child.id)))
    .map(({ id, kind, name }) => ({ id, kind, name }));
}

// The question without the methods and concepts it names by name, for finding an instrument in it: "seafloor
// pressure geodesy" and "fiber-optic sensing" name methods, not a pressure gauge or a cable. A question that only
// uses a method's words ("the tidal pressure gauge") keeps them.
const NAME_IN_TEXT = TERMS.filter((term) => !["site", "feature"].includes(term.kind)).flatMap((term) =>
  [...new Set([term.name, term.name.replace(/\s*\([^)]*\)/g, "")].map(words).filter((n) => n.length >= 4))]
    .map((name) => new RegExp(`(?<![\\p{L}\\p{N}])${name.split(" ").map(escape).join("[^\\p{L}\\p{N}]+")}(?![\\p{L}\\p{N}])`, "giu")));
export function withoutNamedTerms(question) {
  let rest = String(question || "");
  for (const rx of NAME_IN_TEXT) rest = rest.replace(rx, " ");
  return rest;
}

// The distinctive places a question names (Pythia's Oasis, the Inferno vent): their papers join its evidence.
export const featuresIn = (question) => TERMS.filter((term) => term.kind === "feature" && term.rx.test(String(question || "")))
  .map(({ id, name }) => ({ id, name }));

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

// Whether a question names an instrument: a type ("hydrophone") or a code, but not a site written in capitals
// ("ASHES", "SHR"), which questionCodes takes for a code.
export function instrumentAsked({ types = [], codes = [] } = {}) {
  const sites = TERMS.filter((term) => term.kind === "site");
  return types.length > 0 || codes.some((code) => !sites.some((site) => site.rx.test(code)));
}

const ASKS_PAPERS =/\b(?:which|what|list|any|find|show|name)\s+(?:[\w-]+\s+){0,2}(?:papers?|studies|publications?|articles?|research)\b|\b(?:papers?|studies|publications?|articles?)\s+(?:that|which|have|has|about|on)\b|^\s*(?:papers?|publications?|studies)\b|\bwho\s+(?:has|have)\b|\bresearch\s+(?:has|have)\s+been\b/i;
const OVERVIEW_ASK = /\b(?:tell me (?:more )?about|what do we know about|describe|(?:an? )?overview of|introduc\w* to|summar\w*|what(?:'s| is) (?:at|known about|there at))\b|^\s*(?:what|where) is (?:the )?(?:southern hydrate ridge|hydrate ridge|axial(?: seamount)?|ashes|the international district|slope base|axial base)\s*\??\s*$/i;
const PROFILE_ASK = /\b(?:methods?|techniques?|approach(?:es)?|analy[sz]\w*|topics?|features?|processes|concepts?|stud(?:y|ies|ied)|investigat\w*|sensors?|instruments?|data from)\b/i;
const USES_ASK = /\b(?:us(?:e|es|ed|ing)|mention(?:s|ed)?|data from|analy[sz](?:e|es|ed))\b/i;
const METHOD_ASK = /\b(?:methods?|techniques?|approach(?:es)?|analy[sz](?:e|es|ed|is|ing)|tools?)\b/i;

// What a question asks of the links:
// - profile: a paper's methods, concepts, sites and sensors ("What methods does Bartlow et al. (2020) use?");
// - sensor_methods: the methods applied to an instrument's data (the papers that used it, with their methods);
// - topic: the papers that applied a method or studied a concept (rca: with RCA data);
// - site: the papers about a site.
// An instrument's papers ("which papers used HYSB1") stay with papersFor; null when none of these.
export function linkPlan(question, { instrument = false } = {}) {
  const q = String(question || "");
  // A paper's own links answer what it applies or studies; a summary ("tell me about", "what is it about") is
  // answered from its abstract and passages, which the links' outline crowded out (summary key points 88% to 70%).
  const paper = authorYear(q);
  if (paper && PROFILE_ASK.test(q)) return { kind: "profile", ...paper };
  if (paper) return null;
  const terms = linkTermsIn(q);
  const topics = terms.filter((term) => term.kind !== "site");
  const sites = terms.filter((term) => term.kind === "site");
  // A question naming an instrument is about that instrument: its words ("the tidal pressure gauge") also match
  // methods (seafloor pressure geodesy), which are not what it asks.
  if (instrument) return METHOD_ASK.test(q) ? { kind: "sensor_methods" } : ASKS_PAPERS.test(q) ? { kind: "sensor_papers" } : null;
  // "Tell me about Southern Hydrate Ridge": the general search answers; the site's recent papers join its evidence.
  if (!ASKS_PAPERS.test(q)) {
    return sites.length && !topics.length && OVERVIEW_ASK.test(q) ? { kind: "site_overview", terms: sites } : null;
  }
  if (topics.length) return { kind: "topic", terms: topics, sites, rca: asksRcaData(q) };
  // "Which papers used the Central Caldera acoustic transponders": a question about using or mentioning something
  // asks about an instrument, even one whose name the instrument types do not know; the instrument lookup finds it.
  if (USES_ASK.test(q)) return { kind: "sensor_papers" };
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
// The record's header already gives the paper's title, so the text starts at what the link says; a long list (every
// paper about Axial Seamount) keeps each record short to fit.
export function listRecord(hit, { withMethods = false } = {}) {
  const link = hit.metadata?.link || {};
  const used = (link.sensors_used || []).length ? ` It used data from RCA sensors: ${link.sensors_used.slice(0, 6).join(", ")}.` : "";
  const methods = withMethods && (link.methods || []).length ? ` Methods this paper applies (its links): ${link.methods.join("; ")}.` : "";
  let text = String(hit.text || "");
  const title = String(hit.title || "");
  if (title && text.startsWith(title)) text = text.slice(title.length).replace(/^\s*\(\s*(?:\d{4}|n\.d\.)\s*\)\s*/, `(${link.publication_year ?? "n.d."}) `);
  const room = link.predicate === "ABOUT_SITE" ? 220 : 420;
  return { ...hit, text: `${text.slice(0, room)}${used}${methods}`, layer: true, paperList: true };
}

// A long list (310 papers about Axial Seamount) is answered with its most recent papers: the newest RECENT, with the
// count and years of the rest. One record a paper.
export const RECENT = 30;
export function recentPapers(hits, limit = RECENT) {
  const seen = new Set();
  const papers = hits.filter((hit) => {
    const key = hit.metadata?.node_local_id || hit.chunk_id;
    return !seen.has(key) && seen.add(key);
  });
  const year = (hit) => Number(hit.metadata?.link?.publication_year) || 0;
  const sorted = papers.length > limit ? [...papers].sort((a, b) => year(b) - year(a)) : papers;
  const older = sorted.slice(limit);
  const years = older.map(year).filter(Boolean);
  return { shown: sorted.slice(0, limit), total: papers.length, older: older.length,
    olderYears: years.length ? [Math.min(...years), Math.max(...years)] : null };
}

// The list added after the answer, straight from the links (the model writes the overview, not the list, so no paper
// is dropped for want of room): the papers shown, each with its year and link, and what the links judged.
export function linkAppendix(plan, hits) {
  const links = hits.filter((hit) => hit.collection_id === "literature_links" && hit.metadata?.link);
  if (!plan || !links.length) return "";
  const line = (hit, note = "") => {
    const link = hit.metadata.link;
    const url = (hit.citations || []).map((c) => c.url).find((u) => /^https?:/.test(u || ""));
    return `- ${hit.title} (${link.publication_year ?? "n.d."})${note ? `: ${note}` : ""}${url ? ` ${url}` : ""}`;
  };
  const caveat = "_From the literature links, judged by rule from each paper's own words; check a paper before relying on it._";
  if (plan.kind === "sensor_papers") {
    const used = recentPapers(links.filter((hit) => hit.metadata.link.predicate === "USES_SENSOR"), 200).shown;
    const mentioned = recentPapers(links.filter((hit) => hit.metadata.link.predicate === "MENTIONS_SENSOR"), 200).shown;
    return [`**Papers the links say used its data (${used.length})**`, ...used.map((hit) => line(hit)),
      ...(mentioned.length ? ["", `**Papers the links say only mention it (${mentioned.length})**`, ...mentioned.map((hit) => line(hit))] : []),
      "", caveat].join("\n");
  }
  if (plan.kind === "sensor_methods") {
    const by = new Map();
    for (const hit of links.filter((h) => h.metadata.link.predicate === "USES_SENSOR")) {
      for (const method of hit.metadata.link.methods || []) by.set(method, [...(by.get(method) || []), hit]);
    }
    if (!by.size) return "";
    return ["**Methods the links give for the papers that used its data**",
      ...[...by].sort((a, b) => b[1].length - a[1].length).map(([method, papers]) =>
        `- ${method}: ${papers.map((hit) => `${hit.title} (${hit.metadata.link.publication_year ?? "n.d."})`).join("; ")}`),
      "", caveat].join("\n");
  }
  if (plan.kind === "profile") {
    const rows = (predicate) => [...new Set(links.filter((h) => h.metadata.link.predicate === predicate).map((h) => h.metadata.link.target_name))];
    const parts = [["Methods it applies", rows("APPLIES_METHOD")], ["What it studies", rows("STUDIES_CONCEPT")], ["Sites", rows("ABOUT_SITE")],
      ["RCA sensors whose data it used", rows("USES_SENSOR")]].filter(([, xs]) => xs.length);
    return parts.length ? ["**The paper's literature links**", ...parts.map(([label, xs]) => `- ${label}: ${xs.join("; ")}`), "", caveat].join("\n") : "";
  }
  if (plan.kind === "site_overview") {
    const { shown, total } = recentPapers(links, 10);
    return [`**Recent papers about ${plan.terms.map((t) => t.name).join(", ")} (${shown.length} of the ${total} the links give; ask "which papers are about it" for more)**`,
      ...shown.map((hit) => line(hit)), "", caveat].join("\n");
  }
  const { shown, total, older, olderYears } = recentPapers(links);
  const names = plan.terms.map((term) => term.name).join(", ");
  const at = (plan.sites || []).length ? ` at ${plan.sites.map((site) => site.name).join(", ")}` : "";
  const what = plan.kind === "site" ? `about ${names}` : `that ${plan.terms.some((t) => t.kind === "method") ? "applied" : "studied"} ${names}${at}${plan.rca ? " with RCA data" : ""}`;
  const asked = new Set(plan.terms.map((term) => term.name));
  return [older ? `**The ${shown.length} most recent of the ${total} papers the links give ${what}**` : `**The ${total} papers the links give ${what}**`,
    ...shown.map((hit) => line(hit, asked.has(hit.metadata.link.target_name) ? "" : hit.metadata.link.target_name)),
    ...(older ? ["", `${older} older papers (${olderYears ? olderYears.join("–") : "undated"}) are not listed: ask about a narrower topic, a site within it, or a period to see them.`] : []),
    "", caveat].join("\n");
}

// What the answer is told to do with the links.
export function linkInstruction(plan) {
  if (!plan) return "";
  const judged = "The links were made by rule from each paper's own words (its title, abstract or full text), so read each record's quote:";
  if (plan.kind === "profile") {
    return `The evidence holds the literature links of the paper asked about, under 'Literature links of': the methods it applies, the concepts and features it studies, the sites it is about and the RCA sensors it used or mentions, each with how it was found and a quote. ${judged} answer from those that the quote supports, citing the paper (for a methods question, the methods; for what it studies, the concepts and features), and leave out a link whose quote shows the paper only mentions it.`;
  }
  // The full list is added after the answer (linkAppendix): the answer is the overview, not the list.
  const listed = "The system adds the list of these papers from the links after your answer, so do not list them all and do not add a list heading of your own: write a short overview (a few sentences, grouped by theme) naming the most notable papers with their citations.";
  if (plan.kind === "sensor_methods") {
    return `The question asks which methods have been applied to an instrument's data. Each literature-link record of a paper that used the instrument's data ends with the methods that paper applies. Answer with the methods, each with the papers that applied it to this instrument's data (title and citation); a paper that only mentions the instrument does not count. ${judged} a paper whose quote does not show it used the data does not count. The system adds the methods-by-paper list from the links after your answer; your answer is the summary.`;
  }
  if (plan.kind === "sensor_papers") {
    return `The question asks which papers used an instrument's data. Literature-link records in the evidence give each link's judgment, made by rule from the paper's own words: the paper 'used data from' the instrument or 'mentions, without analyzing its data,' it, with why and a quote. ${listed} Say what the papers that used its data did with it. If a record's quote plainly shows its judgment is wrong (a 'used' paper that only cites the instrument), say so. A paper found by meaning rather than by a link (a full-text passage) that plainly analyzed the instrument's data may be added by title.`;
  }
  if (plan.kind === "topic") {
    const names = plan.terms.map((term) => term.name).join(", ");
    const method = plan.terms.some((term) => term.kind === "method");
    const verb = method ? "applied" : "studied";
    return `The question asks which papers ${verb} ${names}${plan.rca ? " with RCA or OOI data" : ""}. Literature-link records in the evidence each say a paper ${method ? "applies the method" : "studies"} it and how that was found${plan.rca ? ", and which RCA sensors' data the paper used" : ""}; when there are many, they are the most recent. ${judged} ${listed} Say what these papers did${plan.rca ? " and with which RCA data" : ""}, and point out any whose quote shows it only mentions or cites ${names}. Only scientific papers count.`;
  }
  return `The question asks which papers are about ${plan.terms.map((term) => term.name).join(", ")}. Literature-link records in the evidence each say a paper is about the site (its title or abstract names it, or the RCA sensors whose data it used are there); when there are many, they are the most recent. ${listed} Say what research these papers cover (the main themes and instruments). Only scientific papers count.`;
}
