-- K02: a hidden cell is empty and a shown row is whole (AC26; decision D30). Where a row is hidden whole (the round and group follow-up, a method in a round or in the test, a segment, the minimum detectable effect) its count
-- is empty, and where it is hidden a column at a time (the round's operation, the product's purchases) a row with nothing hidden has every count. A violation is the table and the key of the row.
SELECT 'fact_round_group' AS table_name, round_key || '/' || group_key || '/' || segment_key AS cell FROM star_fact_round_group WHERE suppressed = 1 AND (customers IS NOT NULL OR buyers IS NOT NULL OR buyers_of_listed IS NOT NULL OR spend IS NOT NULL)
UNION ALL
SELECT 'fact_method_round', method_key || '/' || variant_key || '/' || round_key || '/' || seal_state FROM star_fact_method_round WHERE suppressed = 1 AND (pairs IS NOT NULL OR hit_rate IS NOT NULL OR recall IS NOT NULL OR precision IS NOT NULL OR ndcg IS NOT NULL OR coverage IS NOT NULL)
UNION ALL
SELECT 'fact_method_total', method_key || '/' || variant_key || '/' || seal_state FROM star_fact_method_total WHERE suppressed = 1 AND (pairs IS NOT NULL OR hit_rate IS NOT NULL OR ci_low IS NOT NULL OR ci_high IS NOT NULL OR wilson_low IS NOT NULL OR wilson_high IS NOT NULL OR recall IS NOT NULL OR precision IS NOT NULL OR ndcg IS NOT NULL OR coverage IS NOT NULL)
UNION ALL
SELECT 'fact_segment', method_key || '/' || variant_key || '/' || segment_key || '/' || seal_state FROM star_fact_segment WHERE suppressed = 1 AND (pairs IS NOT NULL OR hit_rate IS NOT NULL OR ci_low IS NOT NULL OR ci_high IS NOT NULL)
UNION ALL
SELECT 'fact_mde', metric || '/' || holdout_share || '/' || seal_state FROM star_fact_mde WHERE suppressed = 1 AND (holdout_size IS NOT NULL OR mde IS NOT NULL OR mde_relative IS NOT NULL)
UNION ALL
SELECT 'fact_offer_product', round_key || '/' || product_key || '/' || source_key FROM star_fact_offer_product WHERE suppressed = 1 AND bought_by IS NOT NULL
UNION ALL
SELECT 'fact_round_ops', round_key FROM star_fact_round_ops WHERE (suppressed = 0 AND (base IS NULL OR offer IS NULL OR control IS NULL OR new_assignments IS NULL OR delivered IS NULL OR buyers_outside_base IS NULL))
   OR (suppressed = 1 AND base IS NOT NULL AND offer IS NOT NULL AND control IS NOT NULL AND new_assignments IS NOT NULL AND delivered IS NOT NULL AND buyers_outside_base IS NOT NULL);
