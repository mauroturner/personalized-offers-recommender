-- The five covariables of the balance (ref_covariate). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_covariate;

CREATE TABLE star_dim_covariate AS
SELECT covariate_key, label_es, unit_es FROM ref_covariate ORDER BY covariate_key;
