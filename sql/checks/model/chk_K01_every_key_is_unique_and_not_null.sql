-- K01: the key of every published table is unique and has no empty part (AC26). A violation is the table and how many rows share the key.
SELECT 'dim_date' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_date GROUP BY date_key HAVING COUNT(*) > 1 OR date_key IS NULL
UNION ALL
SELECT 'dim_round' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_round GROUP BY round_key HAVING COUNT(*) > 1 OR round_key IS NULL
UNION ALL
SELECT 'dim_product' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_product GROUP BY product_key HAVING COUNT(*) > 1 OR product_key IS NULL
UNION ALL
SELECT 'dim_method' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_method GROUP BY method_key HAVING COUNT(*) > 1 OR method_key IS NULL
UNION ALL
SELECT 'dim_variant' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_variant GROUP BY variant_key HAVING COUNT(*) > 1 OR variant_key IS NULL
UNION ALL
SELECT 'dim_source' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_source GROUP BY source_key HAVING COUNT(*) > 1 OR source_key IS NULL
UNION ALL
SELECT 'dim_group' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_group GROUP BY group_key HAVING COUNT(*) > 1 OR group_key IS NULL
UNION ALL
SELECT 'dim_segment' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_segment GROUP BY segment_key HAVING COUNT(*) > 1 OR segment_key IS NULL
UNION ALL
SELECT 'dim_covariate' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_covariate GROUP BY covariate_key HAVING COUNT(*) > 1 OR covariate_key IS NULL
UNION ALL
SELECT 'dim_criterion' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_criterion GROUP BY criterion_key HAVING COUNT(*) > 1 OR criterion_key IS NULL
UNION ALL
SELECT 'dim_pipeline_run' AS table_name, COUNT(*) AS rows_with_this_key FROM star_dim_pipeline_run GROUP BY run_key HAVING COUNT(*) > 1 OR run_key IS NULL
UNION ALL
SELECT 'fact_round_ops' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_round_ops GROUP BY round_key HAVING COUNT(*) > 1 OR round_key IS NULL
UNION ALL
SELECT 'fact_round_group' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_round_group GROUP BY round_key, group_key, segment_key HAVING COUNT(*) > 1 OR round_key IS NULL OR group_key IS NULL OR segment_key IS NULL
UNION ALL
SELECT 'fact_offer_product' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_offer_product GROUP BY round_key, product_key, source_key HAVING COUNT(*) > 1 OR round_key IS NULL OR product_key IS NULL OR source_key IS NULL
UNION ALL
SELECT 'fact_method_round' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_method_round GROUP BY method_key, variant_key, round_key, seal_state HAVING COUNT(*) > 1 OR method_key IS NULL OR variant_key IS NULL OR round_key IS NULL OR seal_state IS NULL
UNION ALL
SELECT 'fact_method_total' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_method_total GROUP BY method_key, variant_key, seal_state HAVING COUNT(*) > 1 OR method_key IS NULL OR variant_key IS NULL OR seal_state IS NULL
UNION ALL
SELECT 'fact_segment' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_segment GROUP BY method_key, variant_key, segment_key, seal_state HAVING COUNT(*) > 1 OR method_key IS NULL OR variant_key IS NULL OR segment_key IS NULL OR seal_state IS NULL
UNION ALL
SELECT 'fact_choice' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_choice GROUP BY candidate HAVING COUNT(*) > 1 OR candidate IS NULL
UNION ALL
SELECT 'fact_balance' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_balance GROUP BY covariate_key, seal_state HAVING COUNT(*) > 1 OR covariate_key IS NULL OR seal_state IS NULL
UNION ALL
SELECT 'fact_experiment' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_experiment GROUP BY metric, test, seal_state HAVING COUNT(*) > 1 OR metric IS NULL OR test IS NULL OR seal_state IS NULL
UNION ALL
SELECT 'fact_mde' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_mde GROUP BY metric, holdout_share, seal_state HAVING COUNT(*) > 1 OR metric IS NULL OR holdout_share IS NULL OR seal_state IS NULL
UNION ALL
SELECT 'fact_rule' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_rule GROUP BY antecedent_key, consequent_key HAVING COUNT(*) > 1 OR antecedent_key IS NULL OR consequent_key IS NULL
UNION ALL
SELECT 'fact_evaluation_summary' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_evaluation_summary GROUP BY criterion_key, seal_state HAVING COUNT(*) > 1 OR criterion_key IS NULL OR seal_state IS NULL
UNION ALL
SELECT 'fact_validation' AS table_name, COUNT(*) AS rows_with_this_key FROM star_fact_validation GROUP BY run_key, rule_id HAVING COUNT(*) > 1 OR run_key IS NULL OR rule_id IS NULL;
