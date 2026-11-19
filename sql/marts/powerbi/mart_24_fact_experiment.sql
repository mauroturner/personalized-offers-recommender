-- The A/A of the sealed control group and the calibration of each test (eval_experiment). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_experiment;

CREATE TABLE star_fact_experiment AS
SELECT metric, kind AS test, aa_diff, aa_p, aa_ci_low, aa_ci_high, calibration_rejection, seal_state FROM eval_experiment ORDER BY metric, kind, seal_state;
