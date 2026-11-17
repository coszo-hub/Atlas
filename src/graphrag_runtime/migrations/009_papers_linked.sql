-- The papers linked to a sensor in the literature-links collection (build_literature_links.py): those that name it
-- (station code, a range taking it in, its reference designator) and those that describe it (its site and kind of
-- instrument in one passage), from abstracts and full text. The terms may be any of the sensor's identities: a
-- station code (HYS14), a designator, its inventory ID (EARTHSCOPE-OO-HYS14) or its instrument record's node
-- (INSTRUMENT-…), which reach the links' sensor node through the identifiers they share. One row a paper, with the
-- link's evidence passage; papers naming the sensor first, then the most passages, then the newest.

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
WITH active AS (
    SELECT build_id FROM graphrag.active_corpus WHERE singleton
), wanted AS (
    SELECT DISTINCT lower(t) AS term FROM unnest(terms[1:12]) t WHERE t ~ '^[A-Za-z0-9._-]{3,60}$'
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
), targets AS (
    SELECT DISTINCT n.node_pk, n.local_id FROM graphrag.nodes n JOIN active a USING (build_id)
    WHERE n.collection_id = 'literature_links'
      AND n.representative_payload->>'entity_type' = 'sensor'
      AND (lower(n.local_id) IN (SELECT id FROM seed_ids)
           OR EXISTS (SELECT 1 FROM graphrag.node_identifiers i
                      WHERE i.node_pk = n.node_pk AND lower(i.identifier) IN (SELECT id FROM seed_ids)))
), links AS (
    SELECT DISTINCT ON (e.source_node_pk, e.target_node_pk)
           e.source_node_pk AS paper_pk, e.target_node_pk, e.predicate, e.payload, t.local_id AS target_local_id
    FROM graphrag.edge_records e JOIN targets t ON t.node_pk = e.target_node_pk
    WHERE e.predicate IN ('NAMES_SENSOR', 'DESCRIBES_SENSOR')
    ORDER BY e.source_node_pk, e.target_node_pk, e.predicate DESC
), per_paper AS (
    -- A paper linked to two of the sensors asked (HYS14 and its designator's record) is one row, its strongest link.
    SELECT DISTINCT ON (l.paper_pk) l.*
    FROM links l
    ORDER BY l.paper_pk, (l.predicate = 'NAMES_SENSOR') DESC, (l.payload->>'passages')::integer DESC NULLS LAST
)
SELECT c.chunk_pk, c.collection_id, c.chunk_id, p.local_id, c.title, c.body, c.source_url, c.locator,
       p.local_id, p.display_name, coalesce(p.source_url, c.source_url),
       '[]'::jsonb,
       coalesce(lower(p.representative_payload->>'doi'), p.local_id),
       coalesce((l.payload->>'passages')::integer, 1),
       ARRAY[l.target_local_id],
       l.predicate,
       jsonb_build_object('match', l.payload->'match', 'layers', l.payload->'layers', 'passages', l.payload->'passages',
                          'sensors_sharing_description', l.payload->'sensors_sharing_description',
                          'publication_year', p.representative_payload->'publication_year',
                          'evidence_chunk_id', l.payload->'evidence_chunk_id', 'evidence_page', l.payload->'evidence_page')
FROM per_paper l
JOIN graphrag.nodes p ON p.node_pk = l.paper_pk
JOIN LATERAL (
    -- The link's evidence passage: the links collection's chunk for this paper and this sensor.
    SELECT c.* FROM graphrag.chunks c
    JOIN graphrag.chunk_links d ON d.chunk_pk = c.chunk_pk AND d.link_type = 'DOCUMENT' AND d.target_node_pk = l.paper_pk
    JOIN graphrag.chunk_links t ON t.chunk_pk = c.chunk_pk AND t.link_type = 'ENTITY' AND t.target_node_pk = l.target_node_pk
    WHERE c.collection_id = 'literature_links'
    LIMIT 1
) c ON true
ORDER BY (l.predicate = 'NAMES_SENSOR') DESC, coalesce((l.payload->>'passages')::integer, 1) DESC,
         (p.representative_payload->>'publication_year') DESC NULLS LAST, p.local_id
LIMIT greatest(1, least(coalesce(result_limit, 30), 50))
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'graphrag_api_role') THEN
        GRANT EXECUTE ON FUNCTION graphrag_api.papers_linked(text[], integer) TO graphrag_api_role;
    END IF;
END $$;
