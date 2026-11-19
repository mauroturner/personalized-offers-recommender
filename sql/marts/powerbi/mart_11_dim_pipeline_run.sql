-- The runs of the flow. ``export.export_run_table`` runs this file alone when a run closes. Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_pipeline_run;

CREATE TABLE star_dim_pipeline_run AS
SELECT run_key, started_at, finished_at, status, delivery_id, as_of, config_sha256, round_id, peak_working_set_mb, memory_counter, message FROM pipeline_runs ORDER BY run_key;
