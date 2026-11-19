-- R19: every fact_evaluation_summary[criterion_key] is a dim_criterion[criterion_key] (AC26). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.criterion_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_evaluation_summary AS f
WHERE f.criterion_key IS NULL OR f.criterion_key NOT IN (SELECT criterion_key FROM star_dim_criterion)
GROUP BY f.criterion_key;
