-- R14: every fact_offer_product[source_key] is a dim_source[source_key] (AC26). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.source_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_offer_product AS f
WHERE f.source_key IS NULL OR f.source_key NOT IN (SELECT source_key FROM star_dim_source)
GROUP BY f.source_key;
