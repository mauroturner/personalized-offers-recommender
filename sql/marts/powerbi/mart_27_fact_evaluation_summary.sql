-- The ten criteria with their verdicts, the same texts as the summary (eval_criteria). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_evaluation_summary;

CREATE TABLE star_fact_evaluation_summary AS
SELECT criterion_id AS criterion_key, tested_value_es, point_value, ci_low, ci_high, passed, seen_by_research, seen_by_planner, verdict_es, seal_state FROM eval_criteria ORDER BY criterion_id, seal_state;
