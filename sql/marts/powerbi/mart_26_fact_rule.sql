-- The pair rules with the highest rule_lift and enough support (ref_rule). Unrelated: it has two product keys. Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_fact_rule;

CREATE TABLE star_fact_rule AS
SELECT antecedent_key, consequent_key, antecedent_es, consequent_es, support, confidence, rule_lift FROM ref_rule ORDER BY rule_lift DESC, support DESC, antecedent_key, consequent_key;
