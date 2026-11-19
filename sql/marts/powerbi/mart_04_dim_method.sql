-- The list, the chosen model and the baselines (ref_method). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_method;

CREATE TABLE star_dim_method AS
SELECT method_key, label_es, role_es FROM ref_method ORDER BY method_key;
