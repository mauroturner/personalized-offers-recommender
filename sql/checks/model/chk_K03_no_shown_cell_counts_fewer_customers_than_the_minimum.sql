-- K03: no cell that counts customers and is shown has fewer than :min_cell_customers (AC26; decisions D30). A violation is the table and the key of the cell.
SELECT 'fact_round_ops' AS table_name, round_key AS cell FROM star_fact_round_ops
WHERE base < :min_cell_customers OR offer < :min_cell_customers OR control < :min_cell_customers OR new_assignments < :min_cell_customers OR delivered < :min_cell_customers OR buyers_outside_base < :min_cell_customers
UNION ALL
SELECT 'fact_round_group', round_key || '/' || group_key || '/' || segment_key FROM star_fact_round_group WHERE customers < :min_cell_customers OR buyers < :min_cell_customers OR buyers_of_listed < :min_cell_customers
UNION ALL
SELECT 'fact_offer_product', round_key || '/' || product_key || '/' || source_key FROM star_fact_offer_product WHERE offered_to < :min_cell_customers OR bought_by < :min_cell_customers
UNION ALL
SELECT 'fact_method_round', method_key || '/' || variant_key || '/' || round_key || '/' || seal_state FROM star_fact_method_round WHERE pairs < :min_cell_customers
UNION ALL
SELECT 'fact_method_total', method_key || '/' || variant_key || '/' || seal_state FROM star_fact_method_total WHERE pairs < :min_cell_customers
UNION ALL
SELECT 'fact_segment', method_key || '/' || variant_key || '/' || segment_key || '/' || seal_state FROM star_fact_segment WHERE pairs < :min_cell_customers
UNION ALL
SELECT 'fact_mde', metric || '/' || holdout_share || '/' || seal_state FROM star_fact_mde WHERE holdout_size < :min_cell_customers;
