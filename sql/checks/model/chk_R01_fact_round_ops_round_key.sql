-- R01: every fact_round_ops[round_key] is a dim_round[round_key] (AC26). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.round_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_round_ops AS f
WHERE f.round_key IS NULL OR f.round_key NOT IN (SELECT round_key FROM star_dim_round)
GROUP BY f.round_key;
