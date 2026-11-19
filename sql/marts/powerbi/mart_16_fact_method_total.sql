-- Each method and variant over the whole test (eval_methods), with the cells under :min_cell_customers pairs hidden (plan section 19; decision D30). Built by export.build_powerbi_marts inside its transaction,
-- after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_method_total;

CREATE TABLE star_fact_method_total AS
WITH cells AS (
    SELECT method, variant, seal_state, pairs, hit_rate, ci_low, ci_high, wilson_low, wilson_high, recall, precision, ndcg, coverage, (pairs < :min_cell_customers) AS suppressed
    FROM eval_methods
    WHERE round_id = 'all'
)
SELECT method AS method_key, variant AS variant_key,
       CASE WHEN suppressed THEN NULL ELSE pairs END AS pairs, CASE WHEN suppressed THEN NULL ELSE hit_rate END AS hit_rate, CASE WHEN suppressed THEN NULL ELSE ci_low END AS ci_low,
       CASE WHEN suppressed THEN NULL ELSE ci_high END AS ci_high, CASE WHEN suppressed THEN NULL ELSE wilson_low END AS wilson_low, CASE WHEN suppressed THEN NULL ELSE wilson_high END AS wilson_high,
       CASE WHEN suppressed THEN NULL ELSE recall END AS recall, CASE WHEN suppressed THEN NULL ELSE precision END AS precision, CASE WHEN suppressed THEN NULL ELSE ndcg END AS ndcg,
       CASE WHEN suppressed THEN NULL ELSE coverage END AS coverage, seal_state, suppressed
FROM cells
ORDER BY method_key, variant_key, seal_state;
