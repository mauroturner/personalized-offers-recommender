-- What a control group of 10, 20 and 30 % could see (eval_mde), with the sizes under :min_cell_customers hidden (plan section 19; decision D30). Built by export.build_powerbi_marts inside its transaction,
-- after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_mde;

CREATE TABLE star_fact_mde AS
WITH cells AS (
    SELECT metric, holdout_share, seal_state, holdout_size, mde, mde_relative, (holdout_size < :min_cell_customers) AS suppressed FROM eval_mde
)
SELECT metric, holdout_share, CASE WHEN suppressed THEN NULL ELSE holdout_size END AS holdout_size, CASE WHEN suppressed THEN NULL ELSE mde END AS mde,
       CASE WHEN suppressed THEN NULL ELSE mde_relative END AS mde_relative, seal_state, suppressed
FROM cells
ORDER BY metric, holdout_share, seal_state;
