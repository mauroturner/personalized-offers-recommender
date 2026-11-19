-- What the closing evaluation found (plan sections 5 and 16; decisions D15, D16, D19, D21; risk item 1: the test is evaluated once).
-- ``seal_state`` says what a row is: ``sealed`` (computed with the sealed configuration, written once, the same rows that the test part of the seal rebuilds) or ``post_seal`` (computed with another
-- configuration: it is kept apart, never replaces a sealed row and is replaced by the next post-seal evaluation). The sealed rows are insert-only in the database itself: three triggers each, which look
-- only at the sealed ones (the key of every table has ``seal_state`` in it, so a post-seal row is another row).
-- ``eval_pairs`` has customer numbers: it stays in ``data/`` and nothing published reads it (decision D30); the independent evaluation reads it to recompute.

CREATE TABLE IF NOT EXISTS eval_pairs (
    round_id TEXT NOT NULL REFERENCES rounds (round_id),
    customer_id INTEGER NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('offer_list', 'chosen_discovery', 'b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6')),
    variant TEXT NOT NULL CHECK (variant IN ('unrestricted', 'new_only')),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    segment TEXT NOT NULL CHECK (segment IN ('bulk|repeat', 'bulk|one_invoice', 'retail|repeat', 'retail|one_invoice')),
    hit INTEGER NOT NULL CHECK (hit IN (0, 1)),
    recall REAL NOT NULL CHECK (recall BETWEEN 0 AND 1),
    precision REAL NOT NULL CHECK (precision BETWEEN 0 AND 1),
    ndcg REAL NOT NULL CHECK (ndcg BETWEEN 0 AND 1),
    test_products INTEGER NOT NULL CHECK (test_products >= 1),
    PRIMARY KEY (round_id, customer_id, method, variant, seal_state)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS eval_methods (
    method TEXT NOT NULL CHECK (method IN ('offer_list', 'chosen_discovery', 'b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6')),
    variant TEXT NOT NULL CHECK (variant IN ('unrestricted', 'new_only')),
    round_id TEXT NOT NULL,                                          -- a round, or 'all' for the rounds of the test
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    pairs INTEGER NOT NULL CHECK (pairs >= 0),
    hit_rate REAL CHECK (hit_rate IS NULL OR hit_rate BETWEEN 0 AND 1),
    ci_low REAL,                                                     -- the 95 % interval by resampling customers: only in the 'all' rows
    ci_high REAL,
    wilson_low REAL,
    wilson_high REAL,
    recall REAL,
    precision REAL,
    ndcg REAL,
    coverage REAL CHECK (coverage IS NULL OR coverage >= 0),
    PRIMARY KEY (method, variant, round_id, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_segments (
    method TEXT NOT NULL CHECK (method IN ('offer_list', 'chosen_discovery', 'b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6')),
    variant TEXT NOT NULL CHECK (variant IN ('unrestricted', 'new_only')),
    segment TEXT NOT NULL CHECK (segment IN ('bulk|repeat', 'bulk|one_invoice', 'retail|repeat', 'retail|one_invoice')),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    pairs INTEGER NOT NULL CHECK (pairs >= 1),
    customers INTEGER NOT NULL CHECK (customers >= 1),               -- a published cell with fewer than [privacy] min_cell_customers customers is hidden when it is exported (D30)
    hit_rate REAL NOT NULL CHECK (hit_rate BETWEEN 0 AND 1),
    ci_low REAL NOT NULL,
    ci_high REAL NOT NULL,
    PRIMARY KEY (method, variant, segment, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_experiment (
    metric TEXT NOT NULL CHECK (metric IN ('m1', 'm2')),
    kind TEXT NOT NULL CHECK (kind IN ('preregistered', 'normal_raw', 'normal_cuped')),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    aa_diff REAL NOT NULL,                                           -- the difference between the groups of an archive where nobody received an offer: an A/A, not an outcome of anything
    aa_p REAL NOT NULL CHECK (aa_p BETWEEN 0 AND 1),
    aa_ci_low REAL NOT NULL,
    aa_ci_high REAL NOT NULL,
    calibration_rejection REAL NOT NULL CHECK (calibration_rejection BETWEEN 0 AND 1),
    PRIMARY KEY (metric, kind, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_mde (
    metric TEXT NOT NULL CHECK (metric IN ('m1', 'm2')),
    holdout_share REAL NOT NULL CHECK (holdout_share > 0 AND holdout_share < 1),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    holdout_size INTEGER NOT NULL CHECK (holdout_size >= 1),
    mde REAL NOT NULL CHECK (mde >= 0),
    mde_relative REAL CHECK (mde_relative IS NULL OR mde_relative >= 0),
    PRIMARY KEY (metric, holdout_share, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_balance (
    covariate TEXT NOT NULL CHECK (covariate IN ('recency_days', 'invoices_365', 'spend_365', 'tenure_days', 'bulk')),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    offer_mean REAL NOT NULL,
    control_mean REAL NOT NULL,
    smd REAL NOT NULL,
    PRIMARY KEY (covariate, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_criteria (
    criterion_id TEXT NOT NULL CHECK (criterion_id IN ('C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10')),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    name_es TEXT NOT NULL,
    tested_value REAL,
    tested_value_es TEXT NOT NULL,                                   -- the quantity that the threshold compares, with its unit: what every table and the design show as «Lo que prueba el umbral»
    point_value REAL,
    ci_low REAL,
    ci_high REAL,
    threshold_es TEXT NOT NULL,
    passed INTEGER CHECK (passed IS NULL OR passed IN (0, 1)),       -- NULL: no threshold (C10)
    seen_by_research TEXT NOT NULL,
    seen_by_planner TEXT NOT NULL,
    verdict_es TEXT NOT NULL,
    PRIMARY KEY (criterion_id, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_choice (
    candidate TEXT NOT NULL,
    round_id TEXT NOT NULL,                                          -- a round of the validation, or 'all'
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    base_model TEXT NOT NULL CHECK (base_model IN ('als', 'cosine', 'rules')),
    size INTEGER NOT NULL,
    regularization REAL,
    trend_weight REAL NOT NULL,
    pairs INTEGER NOT NULL CHECK (pairs >= 0),
    hits INTEGER NOT NULL CHECK (hits >= 0),
    distinct_products INTEGER NOT NULL CHECK (distinct_products >= 0),
    catalogue INTEGER NOT NULL CHECK (catalogue >= 0),
    hit_new REAL,
    coverage REAL,
    kept INTEGER CHECK (kept IS NULL OR kept IN (0, 1)),
    chosen INTEGER CHECK (chosen IS NULL OR chosen IN (0, 1)),
    fit_rounds INTEGER NOT NULL CHECK (fit_rounds >= 1),
    PRIMARY KEY (candidate, round_id, seal_state)
);

CREATE TRIGGER IF NOT EXISTS eval_pairs_no_update BEFORE UPDATE ON eval_pairs WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_pairs es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_pairs_no_delete BEFORE DELETE ON eval_pairs WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_pairs es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_pairs_no_second_insert BEFORE INSERT ON eval_pairs
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_pairs WHERE round_id = NEW.round_id AND customer_id = NEW.customer_id AND method = NEW.method AND variant = NEW.variant AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_pairs es de solo inserción: ese par ya está sellado'); END;

CREATE TRIGGER IF NOT EXISTS eval_methods_no_update BEFORE UPDATE ON eval_methods WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_methods es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_methods_no_delete BEFORE DELETE ON eval_methods WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_methods es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_methods_no_second_insert BEFORE INSERT ON eval_methods
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_methods WHERE method = NEW.method AND variant = NEW.variant AND round_id = NEW.round_id AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_methods es de solo inserción: esa fila ya está sellada'); END;

CREATE TRIGGER IF NOT EXISTS eval_segments_no_update BEFORE UPDATE ON eval_segments WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_segments es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_segments_no_delete BEFORE DELETE ON eval_segments WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_segments es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_segments_no_second_insert BEFORE INSERT ON eval_segments
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_segments WHERE method = NEW.method AND variant = NEW.variant AND segment = NEW.segment AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_segments es de solo inserción: esa fila ya está sellada'); END;

CREATE TRIGGER IF NOT EXISTS eval_experiment_no_update BEFORE UPDATE ON eval_experiment WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_experiment es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_experiment_no_delete BEFORE DELETE ON eval_experiment WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_experiment es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_experiment_no_second_insert BEFORE INSERT ON eval_experiment
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_experiment WHERE metric = NEW.metric AND kind = NEW.kind AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_experiment es de solo inserción: esa fila ya está sellada'); END;

CREATE TRIGGER IF NOT EXISTS eval_mde_no_update BEFORE UPDATE ON eval_mde WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_mde es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_mde_no_delete BEFORE DELETE ON eval_mde WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_mde es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_mde_no_second_insert BEFORE INSERT ON eval_mde
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_mde WHERE metric = NEW.metric AND holdout_share = NEW.holdout_share AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_mde es de solo inserción: esa fila ya está sellada'); END;

CREATE TRIGGER IF NOT EXISTS eval_balance_no_update BEFORE UPDATE ON eval_balance WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_balance es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_balance_no_delete BEFORE DELETE ON eval_balance WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_balance es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_balance_no_second_insert BEFORE INSERT ON eval_balance
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_balance WHERE covariate = NEW.covariate AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_balance es de solo inserción: esa fila ya está sellada'); END;

CREATE TRIGGER IF NOT EXISTS eval_criteria_no_update BEFORE UPDATE ON eval_criteria WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_criteria es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_criteria_no_delete BEFORE DELETE ON eval_criteria WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_criteria es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_criteria_no_second_insert BEFORE INSERT ON eval_criteria
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_criteria WHERE criterion_id = NEW.criterion_id AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_criteria es de solo inserción: ese criterio ya está sellado'); END;

CREATE TRIGGER IF NOT EXISTS eval_choice_no_update BEFORE UPDATE ON eval_choice WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_choice es de solo inserción: lo sellado no se cambia'); END;
CREATE TRIGGER IF NOT EXISTS eval_choice_no_delete BEFORE DELETE ON eval_choice WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_choice es de solo inserción: lo sellado no se borra'); END;
CREATE TRIGGER IF NOT EXISTS eval_choice_no_second_insert BEFORE INSERT ON eval_choice
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_choice WHERE candidate = NEW.candidate AND round_id = NEW.round_id AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_choice es de solo inserción: esa fila ya está sellada'); END;
