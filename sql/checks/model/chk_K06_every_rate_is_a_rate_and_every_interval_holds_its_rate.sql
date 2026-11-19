-- K06: the rates are between 0 and 1, the shares are too and an interval holds the rate it surrounds (AC21, AC26). A violation is the table and the key of the row.
SELECT 'fact_round_ops' AS table_name, round_key AS cell FROM star_fact_round_ops WHERE fallback_share < 0 OR fallback_share > 1
UNION ALL
SELECT 'fact_method_round', method_key || '/' || variant_key || '/' || round_key || '/' || seal_state FROM star_fact_method_round
WHERE hit_rate < 0 OR hit_rate > 1 OR recall < 0 OR recall > 1 OR precision < 0 OR precision > 1 OR ndcg < 0 OR ndcg > 1 OR coverage < 0
UNION ALL
SELECT 'fact_method_total', method_key || '/' || variant_key || '/' || seal_state FROM star_fact_method_total
WHERE hit_rate < 0 OR hit_rate > 1 OR ci_low > hit_rate OR ci_high < hit_rate OR wilson_low > hit_rate OR wilson_high < hit_rate OR coverage < 0
UNION ALL
SELECT 'fact_segment', method_key || '/' || variant_key || '/' || segment_key || '/' || seal_state FROM star_fact_segment WHERE hit_rate < 0 OR hit_rate > 1 OR ci_low > hit_rate OR ci_high < hit_rate;
