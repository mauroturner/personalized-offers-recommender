-- R13: every fact_segment[variant_key] is a dim_variant[variant_key] (AC26). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.variant_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_segment AS f
WHERE f.variant_key IS NULL OR f.variant_key NOT IN (SELECT variant_key FROM star_dim_variant)
GROUP BY f.variant_key;
