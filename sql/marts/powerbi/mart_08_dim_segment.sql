-- The four segments (ref_segment). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_segment;

CREATE TABLE star_dim_segment AS
SELECT segment_key, label_es FROM ref_segment ORDER BY segment_key;
