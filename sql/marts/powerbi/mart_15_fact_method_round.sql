-- Each method and variant in each round of the evaluation (eval_methods), with the small cells hidden and a second one where a method would hide only one (plan section 19; decision D30). Built by
-- export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
-- A cell is hidden when its pairs (the customers of the base that bought in the week) are fewer than :min_cell_customers: then all its numbers are empty. ``fact_method_total`` publishes the pairs of the whole test,
-- which are the sum of the rounds' of the test (the censored round is beside it and not in it), so a method with exactly one hidden round of the test would give it back by subtraction: then the smallest shown round
-- of the test (fewest pairs, then the earliest) is hidden too. The censored round is a group of its own: hidden or shown by its own pairs.
DROP TABLE IF EXISTS star_fact_method_round;

CREATE TABLE star_fact_method_round AS
WITH cells AS (
    SELECT m.method, m.variant, m.round_id, m.seal_state, r.period, m.pairs, m.hit_rate, m.recall, m.precision, m.ndcg, m.coverage, (m.pairs < :min_cell_customers) AS small
    FROM eval_methods AS m
    JOIN ref_round AS r ON r.round_key = m.round_id
),
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY method, variant, seal_state, period) AS hidden,
           ROW_NUMBER() OVER (PARTITION BY method, variant, seal_state, period, small ORDER BY pairs, round_id) AS order_in_kind
    FROM cells
),
decided AS (
    SELECT *, (small = 1 OR (hidden = 1 AND small = 0 AND order_in_kind = 1)) AS suppressed FROM ranked
)
SELECT method AS method_key, variant AS variant_key, round_id AS round_key,
       CASE WHEN suppressed THEN NULL ELSE pairs END AS pairs, CASE WHEN suppressed THEN NULL ELSE hit_rate END AS hit_rate, CASE WHEN suppressed THEN NULL ELSE recall END AS recall,
       CASE WHEN suppressed THEN NULL ELSE precision END AS precision, CASE WHEN suppressed THEN NULL ELSE ndcg END AS ndcg, CASE WHEN suppressed THEN NULL ELSE coverage END AS coverage,
       seal_state, suppressed
FROM decided
ORDER BY method_key, variant_key, round_key, seal_state;
