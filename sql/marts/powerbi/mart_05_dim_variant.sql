-- The two variants of each method (ref_variant). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_variant;

CREATE TABLE star_dim_variant AS
SELECT variant_key, label_es FROM ref_variant ORDER BY variant_key;
