-- The literature links as judged by build_literature_links.py: papers that USE a sensor's data or only MENTION it,
-- the methods they APPLY, the concepts they STUDY, the sites they are ABOUT and the features they name, each link with
-- its evidence passage (a chunk of the links collection). Methods, concepts and sites have broader entries
-- (NARROWER_THAN): asking for one takes in the narrower ones (fiber sensing takes in DAS; Axial Seamount takes in ASHES).
--
-- papers_linked (009) keeps its signature for the deployed Worker and now reads the judged sensor links, used first.
-- paper_links: the papers linked to any of the terms (a sensor's identities, a method, concept or site id), or the
-- links of the papers given, with the predicates asked; rca_only keeps papers that used RCA data.
-- papers_by_author: papers by a first author's surname and year ("Chadwick et al. (2012)").

CREATE OR REPLACE FUNCTION graphrag_api.paper_links(
    terms text[],
    predicates text[] DEFAULT NULL,
    paper_ids text[] DEFAULT NULL,
    rca_only boolean DEFAULT false,
    result_limit integer DEFAULT 40
) RETURNS TABLE (
    chunk_pk bigint, collection_id text, chunk_id text, node_local_id text,
    title text, body text, source_url text, locator text,
    citation_source_id text, citation_title text, citation_url text,
    places jsonb, paper_key text, passages_naming integer, terms_named text[],
    predicate text, link jsonb
) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, graphrag, public
SET statement_timeout = '5s'
AS $$
WITH RECURSIVE active AS (
    SELECT build_id FROM graphrag.active_corpus WHERE singleton
), wanted AS (
    SELECT DISTINCT lower(t) AS term FROM unnest((coalesce(terms, ARRAY[]::text[]))[1:16]) t WHERE t ~ '^[A-Za-z0-9._-]{2,80}$'
), wanted_papers AS (
    SELECT DISTINCT lower(t) AS id FROM unnest((coalesce(paper_ids, ARRAY[]::text[]))[1:12]) t WHERE t ~ '^[A-Za-z0-9._-]{2,80}$'
), seed_nodes AS (
    -- The nodes the terms name, in the instrument records and in the links themselves.
    SELECT n.node_pk FROM graphrag.nodes n JOIN active a USING (build_id)
    WHERE n.collection_id IN ('instruments', 'literature_links') AND lower(n.local_id) IN (SELECT term FROM wanted)
    UNION
    SELECT i.node_pk FROM graphrag.node_identifiers i JOIN graphrag.nodes n USING (node_pk) JOIN active a USING (build_id)
    WHERE n.collection_id IN ('instruments', 'literature_links') AND lower(i.identifier) IN (SELECT term FROM wanted)
), seed_ids AS (
    SELECT lower(i.identifier) AS id FROM graphrag.node_identifiers i WHERE i.node_pk IN (SELECT node_pk FROM seed_nodes)
    UNION SELECT lower(n.local_id) FROM graphrag.nodes n WHERE n.node_pk IN (SELECT node_pk FROM seed_nodes)
    UNION SELECT term FROM wanted
), direct AS (
    SELECT DISTINCT n.node_pk FROM graphrag.nodes n JOIN active a USING (build_id)
    WHERE n.collection_id = 'literature_links'
      AND n.representative_payload->>'entity_type' IN ('sensor', 'method', 'concept', 'site', 'feature')
      AND (lower(n.local_id) IN (SELECT id FROM seed_ids)
           OR EXISTS (SELECT 1 FROM graphrag.node_identifiers i
                      WHERE i.node_pk = n.node_pk AND lower(i.identifier) IN (SELECT id FROM seed_ids)))
), targets AS (
    -- The entries asked for and every narrower one.
    SELECT node_pk, 0 AS depth FROM direct
    UNION
    SELECT e.source_node_pk, t.depth + 1 FROM graphrag.edge_records e JOIN targets t ON e.target_node_pk = t.node_pk
    WHERE e.predicate = 'NARROWER_THAN' AND t.depth < 4
), papers_asked AS (
    SELECT n.node_pk FROM graphrag.nodes n JOIN active a USING (build_id)
    WHERE n.collection_id = 'literature_links' AND n.representative_payload->>'entity_type' = 'paper'
      AND lower(n.local_id) IN (SELECT id FROM wanted_papers)
), links AS (
    SELECT DISTINCT ON (e.source_node_pk, e.target_node_pk, e.predicate)
           e.source_node_pk AS paper_pk, e.target_node_pk, e.predicate, e.payload
    FROM graphrag.edge_records e
    WHERE (e.target_node_pk IN (SELECT node_pk FROM targets) OR e.source_node_pk IN (SELECT node_pk FROM papers_asked))
      AND e.predicate <> 'NARROWER_THAN' AND e.predicate <> 'EVIDENCE_FOR'
      AND (predicates IS NULL OR e.predicate = ANY (predicates))
    ORDER BY e.source_node_pk, e.target_node_pk, e.predicate
), ranked AS (
    SELECT l.*, p.local_id AS paper_local_id, p.display_name AS paper_title, p.source_url AS paper_url,
           p.representative_payload AS paper_payload, t.local_id AS target_local_id, t.display_name AS target_name,
           CASE l.predicate WHEN 'USES_SENSOR' THEN 0 WHEN 'APPLIES_METHOD' THEN 1 WHEN 'STUDIES_CONCEPT' THEN 1
                            WHEN 'ABOUT_SITE' THEN 2 WHEN 'NAMES_SENSOR' THEN 2 WHEN 'MENTIONS_SENSOR' THEN 3 ELSE 4 END AS rank,
           coalesce((l.payload->>'in_title')::boolean, false)::int * 100
             + coalesce((l.payload->>'abstract_mentions')::integer, 0) * 10
             + coalesce((l.payload->>'fulltext_passages')::integer, 0)
             + coalesce((l.payload->>'passages_about_data')::integer, 0) * 5
             + coalesce((l.payload->>'passages')::integer, 0) AS strength
    FROM links l
    JOIN graphrag.nodes p ON p.node_pk = l.paper_pk
    JOIN graphrag.nodes t ON t.node_pk = l.target_node_pk
    WHERE p.representative_payload->>'entity_type' = 'paper'
      AND (NOT rca_only OR coalesce((p.representative_payload->>'uses_rca_data')::boolean, false))
)
SELECT c.chunk_pk, c.collection_id, c.chunk_id, l.paper_local_id, c.title, c.body, c.source_url, c.locator,
       l.paper_local_id, l.paper_title, coalesce(l.paper_url, c.source_url),
       '[]'::jsonb,
       coalesce(lower(l.paper_payload->>'doi'), l.paper_local_id),
       coalesce((l.payload->>'passages')::integer, (l.payload->>'fulltext_passages')::integer, 1),
       ARRAY[l.target_local_id],
       l.predicate,
       l.payload || jsonb_build_object(
           'target', l.target_local_id, 'target_name', l.target_name,
           'publication_year', l.paper_payload->'publication_year', 'citation', l.paper_payload->'citation',
           'uses_rca_data', l.paper_payload->'uses_rca_data', 'sensors_used', l.paper_payload->'sensors_used',
           'methods', l.paper_payload->'methods', 'concepts', l.paper_payload->'concepts', 'sites', l.paper_payload->'sites')
FROM ranked l
JOIN LATERAL (
    -- The link's evidence passage: the links collection's chunk for this paper, this target and this predicate.
    SELECT c.* FROM graphrag.chunks c
    JOIN graphrag.chunk_links d ON d.chunk_pk = c.chunk_pk AND d.link_type = 'DOCUMENT' AND d.target_node_pk = l.paper_pk
    JOIN graphrag.chunk_links t ON t.chunk_pk = c.chunk_pk AND t.link_type = 'ENTITY' AND t.target_node_pk = l.target_node_pk
    WHERE c.collection_id = 'literature_links'
    ORDER BY (c.metadata->>'predicate' = l.predicate) DESC NULLS LAST
    LIMIT 1
) c ON true
ORDER BY l.rank, l.strength DESC, (l.paper_payload->>'publication_year') DESC NULLS LAST, l.paper_local_id
LIMIT greatest(1, least(coalesce(result_limit, 40), 400))
$$;

CREATE OR REPLACE FUNCTION graphrag_api.papers_linked(
    terms text[],
    result_limit integer DEFAULT 30
) RETURNS TABLE (
    chunk_pk bigint, collection_id text, chunk_id text, node_local_id text,
    title text, body text, source_url text, locator text,
    citation_source_id text, citation_title text, citation_url text,
    places jsonb, paper_key text, passages_naming integer, terms_named text[],
    predicate text, link jsonb
) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, graphrag, public
SET statement_timeout = '5s'
AS $$
SELECT * FROM graphrag_api.paper_links(terms, ARRAY['USES_SENSOR', 'MENTIONS_SENSOR', 'NAMES_SENSOR', 'DESCRIBES_SENSOR'],
                                       NULL, false, result_limit)
$$;

CREATE OR REPLACE FUNCTION graphrag_api.papers_by_author(
    surname text,
    pub_year integer DEFAULT NULL,
    result_limit integer DEFAULT 5
) RETURNS TABLE (paper_id text, title text, citation text, publication_year integer)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, graphrag, public
SET statement_timeout = '3s'
AS $$
WITH active AS (
    SELECT build_id FROM graphrag.active_corpus WHERE singleton
)
SELECT n.local_id, n.display_name, n.representative_payload->>'citation',
       (n.representative_payload->>'publication_year')::integer
FROM graphrag.nodes n JOIN active a USING (build_id)
WHERE n.collection_id = 'literature_links' AND n.representative_payload->>'entity_type' = 'paper'
  AND surname ~ '^[[:alpha:]''’ -]{2,40}$'
  AND (pub_year IS NULL OR n.representative_payload->>'publication_year' = pub_year::text)
  -- The first author: the surname near the start of the citation ("Chadwick, W. W." or "William W. Chadwick, ...").
  AND left(n.representative_payload->>'citation', 60) ~* ('(^|[^[:alpha:]])' || regexp_replace(surname, '([^[:alnum:] ])', '\\\1', 'g') || '([^[:alpha:]]|$)')
ORDER BY position(lower(surname) IN lower(n.representative_payload->>'citation')), n.local_id
LIMIT greatest(1, least(coalesce(result_limit, 5), 20))
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'graphrag_api_role') THEN
        GRANT EXECUTE ON FUNCTION graphrag_api.papers_linked(text[], integer) TO graphrag_api_role;
        GRANT EXECUTE ON FUNCTION graphrag_api.paper_links(text[], text[], text[], boolean, integer) TO graphrag_api_role;
        GRANT EXECUTE ON FUNCTION graphrag_api.papers_by_author(text, integer, integer) TO graphrag_api_role;
    END IF;
END $$;
