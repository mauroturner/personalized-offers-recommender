-- The recipes measured in the validation, from the launch part of the seal (ref_choice). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_choice;

CREATE TABLE star_fact_choice AS
SELECT candidate, base_model, params, trend_weight, val_hit_new, val_coverage, kept, chosen, fit_rounds FROM ref_choice ORDER BY candidate;
