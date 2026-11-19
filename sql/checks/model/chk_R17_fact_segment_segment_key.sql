-- R17: every fact_segment[segment_key] is a dim_segment[segment_key] (AC26). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.segment_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_segment AS f
WHERE f.segment_key IS NULL OR f.segment_key NOT IN (SELECT segment_key FROM star_dim_segment)
GROUP BY f.segment_key;
