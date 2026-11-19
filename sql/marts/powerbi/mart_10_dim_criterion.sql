-- The ten criteria with their sealed thresholds (ref_criterion). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_criterion;

CREATE TABLE star_dim_criterion AS
SELECT criterion_key, name_es, threshold_es FROM ref_criterion ORDER BY criterion_key;
