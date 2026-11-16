-- Papers naming an instrument code, now also by a range of station codes and in the abstracts.
--
-- "Which papers use the seismometer at HYS14?" found two papers. Two more name it: the seismicity-detection paper with
-- ocean-bottom DAS writes the Southern Hydrate Ridge summit stations as "HYS11-14" and "HYS12-14" (with a Unicode
-- hyphen), and the trends in low-frequency noise off Oregon name "station HYS14" in an abstract, which the full-text
-- layer does not hold. A code of letters and a number now also matches a range that takes it in, and abstracts are
-- searched too, each its paper's by DOI. Otherwise as 005.

CREATE OR REPLACE FUNCTION graphrag_api.papers_naming(
    terms text[],
    result_limit integer DEFAULT 10
) RETURNS TABLE (
    chunk_pk bigint, collection_id text, chunk_id text, node_local_id text,
    title text, body text, source_url text, locator text,
    citation_source_id text, citation_title text, citation_url text,
    places jsonb, paper_key text, passages_naming integer, terms_named text[]
) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, graphrag, public
SET statement_timeout = '5s'
AS $$
WITH active AS (
    SELECT build_id FROM graphrag.active_corpus WHERE singleton
), wanted AS (
    -- Codes only: letters, digits and hyphens, 3 to 40 characters, at most six.
    SELECT DISTINCT t AS term FROM unnest(terms[1:6]) t WHERE t ~ '^[A-Za-z0-9-]{3,40}$'
), ranged AS (
    -- A station code's letters and number ("HYS14": "HYS", 14), for the ranges a paper writes ("HYS11-14").
    SELECT term, (regexp_match(term, '^([A-Z]+)([0-9]+)$'))[1] AS prefix, (regexp_match(term, '^([A-Z]+)([0-9]+)$'))[2]::integer AS num
    FROM wanted WHERE term ~ '^[A-Z]+[0-9]+$'
), layer AS MATERIALIZED (
    -- The full-text layer and the abstracts, read once for all the terms (one scan per term took 1.8 s each). An
    -- abstract is its paper's by DOI: one paper is known by HYS14 only in its abstract ("The data originate from
    -- station HYS14", the low-frequency noise trends off Oregon).
    SELECT c.chunk_pk, c.body, coalesce(c.metadata->'paper_keys'->>0, lower(c.metadata->>'doi'), c.chunk_id) AS paper_key
    FROM graphrag.chunks c JOIN active a USING (build_id)
    WHERE ((c.collection_id LIKE '%\_fulltext' ESCAPE '\' OR c.metadata ? 'retrieval_layer') AND c.metadata ? 'paper_keys')
       OR c.collection_id = 'literature'
), hit AS (
    SELECT l.chunk_pk, l.paper_key, w.term,
           (length(l.body) - length(replace(l.body, w.term, ''))) / length(w.term) AS n
    FROM layer l JOIN wanted w
      ON strpos(l.body, w.term) > 0 AND l.body ~ ('(^|[^A-Za-z0-9])' || w.term || '($|[^A-Za-z0-9])')
    UNION ALL
    -- A range that takes the code in: "HYS11-14", "HYS12–14" or "HYS11–HYS14" (any hyphen or dash) names HYS14; the
    -- seismicity-detection paper with ocean-bottom DAS writes only "HYS11‐14" and "HYS12‐14" for the summit stations.
    SELECT l.chunk_pk, l.paper_key, r.term, 1 AS n
    FROM layer l JOIN ranged r ON strpos(l.body, r.prefix) > 0
    CROSS JOIN LATERAL regexp_matches(l.body, '(?:^|[^A-Za-z0-9])' || r.prefix || '([0-9]+)\s?[-‐‑–—]\s?(?:' || r.prefix || ')?([0-9]+)(?:$|[^A-Za-z0-9])', 'g') m
    WHERE m[1]::integer < m[2]::integer AND m[2]::integer - m[1]::integer < 50 AND r.num BETWEEN m[1]::integer AND m[2]::integer
), per_chunk AS (
    SELECT chunk_pk, paper_key, sum(n) AS n, array_agg(DISTINCT term ORDER BY term) AS terms_named FROM hit GROUP BY chunk_pk, paper_key
), per_paper AS (
    SELECT paper_key, count(DISTINCT chunk_pk)::integer AS passages_naming,
           (array_agg(chunk_pk ORDER BY n DESC, chunk_pk))[1] AS best,
           array_agg(DISTINCT t ORDER BY t) AS terms_named
    FROM per_chunk, unnest(per_chunk.terms_named) t GROUP BY paper_key
)
SELECT c.chunk_pk, c.collection_id, c.chunk_id, n.local_id, c.title, c.body, c.source_url, c.locator,
       coalesce(citation.local_id, n.local_id), coalesce(citation.display_name, c.title),
       coalesce(citation.source_url, c.source_url, n.source_url),
       coalesce(c.metadata->'places', '[]'::jsonb),
       p.paper_key, p.passages_naming, p.terms_named
FROM per_paper p
JOIN graphrag.chunks c ON c.chunk_pk = p.best
JOIN graphrag.nodes n USING (node_pk)
LEFT JOIN LATERAL (
    SELECT linked.local_id, linked.display_name, linked.source_url
    FROM graphrag.chunk_links cl
    JOIN graphrag.nodes linked ON linked.node_pk = cl.target_node_pk
    WHERE cl.chunk_pk = c.chunk_pk
    ORDER BY CASE cl.link_type
        WHEN 'SOURCE' THEN 1 WHEN 'DOCUMENT' THEN 2 WHEN 'PAGE' THEN 3
        WHEN 'PARENT' THEN 4 ELSE 5 END,
        linked.node_pk
    LIMIT 1
) citation ON true
ORDER BY cardinality(p.terms_named) DESC, p.passages_naming DESC, p.paper_key
LIMIT greatest(1, least(coalesce(result_limit, 10), 20))
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'graphrag_api_role') THEN
        GRANT EXECUTE ON FUNCTION graphrag_api.papers_naming(text[], integer) TO graphrag_api_role;
    END IF;
END $$;
