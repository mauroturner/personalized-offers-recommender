-- R18: every fact_balance[covariate_key] is a dim_covariate[covariate_key] (AC26). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.covariate_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_balance AS f
WHERE f.covariate_key IS NULL OR f.covariate_key NOT IN (SELECT covariate_key FROM star_dim_covariate)
GROUP BY f.covariate_key;
