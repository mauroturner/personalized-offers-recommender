-- The group that gets the list and the control group (ref_group). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_group;

CREATE TABLE star_dim_group AS
SELECT group_key, label_es FROM ref_group ORDER BY group_key;
