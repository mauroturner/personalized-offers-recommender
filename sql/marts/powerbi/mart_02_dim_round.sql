-- The rounds that were built and delivered (ref_round). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_round;

CREATE TABLE star_dim_round AS
SELECT round_key, monday, period, days_observed FROM ref_round ORDER BY round_key;
