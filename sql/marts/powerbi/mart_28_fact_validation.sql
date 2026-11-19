-- What each validation rule said in each run (validation_results). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_validation;

CREATE TABLE star_fact_validation AS
SELECT run_key, rule_id, name_es, severity, scope, aggregation, CASE passed WHEN 1 THEN 'pasa' ELSE 'falla' END AS status, rows_affected FROM validation_results ORDER BY run_key, rule_id;
