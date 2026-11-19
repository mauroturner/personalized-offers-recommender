-- K04: the secondary rule (project 04; decision D30): where a total is published, a group with exactly one hidden cell would give it back by subtraction, so it never has just one. The group of the follow-up is the
-- round and the group of customers, the group of a method's rounds is the method, the variant, the seal state and the rounds of the test (only they add up to the total: the censored round is beside it and has no group), the group of a method's segments is the method, the variant and the seal state, and the group of the products of a round is the round. A violation is the group and its
-- single hidden cell.
SELECT 'fact_round_group' AS table_name, round_key || '/' || group_key AS grp FROM star_fact_round_group GROUP BY round_key, group_key HAVING SUM(suppressed) = 1
UNION ALL
SELECT 'fact_method_round', f.method_key || '/' || f.variant_key || '/' || f.seal_state FROM star_fact_method_round AS f JOIN star_dim_round AS r ON r.round_key = f.round_key
WHERE r.period = 'test'
GROUP BY f.method_key, f.variant_key, f.seal_state HAVING SUM(f.suppressed) = 1
UNION ALL
SELECT 'fact_segment', method_key || '/' || variant_key || '/' || seal_state FROM star_fact_segment GROUP BY method_key, variant_key, seal_state HAVING SUM(suppressed) = 1;
