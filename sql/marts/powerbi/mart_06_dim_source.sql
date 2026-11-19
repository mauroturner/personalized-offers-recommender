-- Where each product of a list comes from (ref_source). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_source;

CREATE TABLE star_dim_source AS
SELECT source_key, label_es FROM ref_source ORDER BY source_key;
