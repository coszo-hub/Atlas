-- papers_by_author (010) also gives each paper's abstract record (its chunk in the literature collection), so a
-- summary question ("Summarize Chadwick et al. (2016).") gets the paper itself by id; a search by its title missed
-- a quarter of them.
DROP FUNCTION IF EXISTS graphrag_api.papers_by_author(text, integer, integer);
CREATE FUNCTION graphrag_api.papers_by_author(
    surname text,
    pub_year integer DEFAULT NULL,
    result_limit integer DEFAULT 5
) RETURNS TABLE (paper_id text, title text, citation text, publication_year integer, abstract_chunk_id text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, graphrag, public
SET statement_timeout = '3s'
AS $$
WITH active AS (
    SELECT build_id FROM graphrag.active_corpus WHERE singleton
)
SELECT n.local_id, n.display_name, n.representative_payload->>'citation',
       (n.representative_payload->>'publication_year')::integer,
       (SELECT c.chunk_id FROM graphrag.chunks c
        JOIN graphrag.chunk_links d ON d.chunk_pk = c.chunk_pk AND d.link_type = 'DOCUMENT'
        JOIN graphrag.nodes dn ON dn.node_pk = d.target_node_pk
        WHERE c.collection_id = 'literature' AND c.build_id = n.build_id AND dn.local_id = n.local_id
        ORDER BY c.chunk_id LIMIT 1)
FROM graphrag.nodes n JOIN active a USING (build_id)
WHERE n.collection_id = 'literature_links' AND n.representative_payload->>'entity_type' = 'paper'
  AND surname ~ '^[[:alpha:]''’ -]{2,40}$'
  AND (pub_year IS NULL OR n.representative_payload->>'publication_year' = pub_year::text)
  AND left(n.representative_payload->>'citation', 60) ~* ('(^|[^[:alpha:]])' || regexp_replace(surname, '([^[:alnum:] ])', '\\\1', 'g') || '([^[:alpha:]]|$)')
ORDER BY position(lower(surname) IN lower(n.representative_payload->>'citation')), n.local_id
LIMIT greatest(1, least(coalesce(result_limit, 5), 20))
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'graphrag_api_role') THEN
        GRANT EXECUTE ON FUNCTION graphrag_api.papers_by_author(text, integer, integer) TO graphrag_api_role;
    END IF;
END $$;
