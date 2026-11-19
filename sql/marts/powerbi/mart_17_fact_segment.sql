-- Each method and variant by segment (eval_segments), with the small cells hidden and a second one where a method would hide only one (plan section 19; decision D30). Built by export.build_powerbi_marts inside
-- its transaction, after the reference tables (ref_*).
-- A cell is hidden when its **customers** (not its pairs: a customer is in several rounds) are fewer than :min_cell_customers: then all its numbers are empty. ``fact_method_total`` publishes the pairs of the
-- whole test, which are the sum of the segments', so a method with exactly one hidden segment would give it back by subtraction: then the smallest shown segment of that method (fewest customers, then the lowest
-- key) is hidden too.
DROP TABLE IF EXISTS star_fact_segment;

CREATE TABLE star_fact_segment AS
WITH cells AS (
    SELECT method, variant, segment, seal_state, pairs, customers, hit_rate, ci_low, ci_high, (customers < :min_cell_customers) AS small
    FROM eval_segments
),
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY method, variant, seal_state) AS hidden,
           ROW_NUMBER() OVER (PARTITION BY method, variant, seal_state, small ORDER BY customers, segment) AS order_in_kind
    FROM cells
),
decided AS (
    SELECT *, (small = 1 OR (hidden = 1 AND small = 0 AND order_in_kind = 1)) AS suppressed FROM ranked
)
SELECT method AS method_key, variant AS variant_key, segment AS segment_key,
       CASE WHEN suppressed THEN NULL ELSE pairs END AS pairs, CASE WHEN suppressed THEN NULL ELSE hit_rate END AS hit_rate, CASE WHEN suppressed THEN NULL ELSE ci_low END AS ci_low,
       CASE WHEN suppressed THEN NULL ELSE ci_high END AS ci_high, seal_state, suppressed
FROM decided
ORDER BY method_key, variant_key, segment_key, seal_state;
