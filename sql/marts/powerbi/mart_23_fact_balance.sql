-- The balance of the control group in the launch cohort (eval_balance). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_balance;

CREATE TABLE star_fact_balance AS
SELECT covariate AS covariate_key, offer_mean, control_mean, smd, seal_state FROM eval_balance ORDER BY covariate, seal_state;
