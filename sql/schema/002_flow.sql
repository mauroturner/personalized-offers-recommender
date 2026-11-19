-- What the flow built and issued, each thing once (plan, section 5; decisions D14, D24; risk item 1: what was issued is not redone).
-- Every table here is insert-only: three triggers refuse, in the database itself and whoever writes, an update, a delete and a second insert of a key that is already there
-- (INSERT OR REPLACE, INSERT OR IGNORE and an upsert included: the trigger of the insert fires before the conflict is resolved), as in project 07. That is what makes the
-- control group a control group: a customer's assignment, and the list that a customer of the control group would have had, are written once and stay as they were.
-- Amounts are decimal text ('12.50'), never floating point; the covariates of the base are floating point and are stored as the exact double. A round is named ``R<Monday>``.

CREATE TABLE IF NOT EXISTS rounds (
    round_id TEXT PRIMARY KEY,
    monday TEXT NOT NULL,
    period TEXT NOT NULL CHECK (period IN ('validation', 'test', 'censored')),
    built_by_run TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    base_size INTEGER NOT NULL CHECK (base_size >= 0),
    offer_size INTEGER NOT NULL CHECK (offer_size >= 0),
    control_size INTEGER NOT NULL CHECK (control_size >= 0),
    CHECK (offer_size + control_size <= base_size)
);

CREATE TABLE IF NOT EXISTS contact_base (
    round_id TEXT NOT NULL REFERENCES rounds (round_id),
    customer_id INTEGER NOT NULL,
    recency_days REAL NOT NULL CHECK (recency_days > 0),               -- days from the last purchase to the Monday of the round
    invoices_365 INTEGER NOT NULL CHECK (invoices_365 >= 1),
    spend_365 REAL NOT NULL,
    tenure_days REAL NOT NULL CHECK (tenure_days > 0),                 -- days from the first purchase to the Monday of the round
    bulk INTEGER NOT NULL CHECK (bulk IN (0, 1)),
    invoices_before INTEGER NOT NULL CHECK (invoices_before >= 1),     -- invoices of the customer in all the history
    segment TEXT NOT NULL CHECK (segment IN ('bulk|repeat', 'bulk|one_invoice', 'retail|repeat', 'retail|one_invoice')),
    PRIMARY KEY (round_id, customer_id)
);

CREATE TABLE IF NOT EXISTS holdout_assignments (
    customer_id INTEGER PRIMARY KEY,
    grp TEXT NOT NULL CHECK (grp IN ('offer', 'control')),
    method TEXT NOT NULL CHECK (method IN ('stratified', 'hash')),
    stratum INTEGER,
    assigned_round TEXT NOT NULL REFERENCES rounds (round_id),
    run_key TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    CHECK ((method = 'stratified') = (stratum IS NOT NULL))              -- the launch draw has its stratum; the hash assignment of a newcomer has none
);

CREATE TABLE IF NOT EXISTS model_registry (
    round_id TEXT NOT NULL REFERENCES rounds (round_id),
    component TEXT NOT NULL CHECK (component IN ('als', 'cosine', 'rules', 'popularity')),
    params_json TEXT NOT NULL CHECK (json_valid(params_json)),
    artifact_path TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    fit_lines INTEGER NOT NULL CHECK (fit_lines >= 1),
    seconds REAL NOT NULL CHECK (seconds >= 0),
    PRIMARY KEY (round_id, component)
);

CREATE TABLE IF NOT EXISTS offer_lists (
    round_id TEXT NOT NULL REFERENCES rounds (round_id),
    customer_id INTEGER NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    stock_code TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('repeat', 'discovery', 'fallback')),
    score REAL NOT NULL,
    grp TEXT NOT NULL CHECK (grp IN ('offer', 'control')),            -- the list of a customer of the control group is the one it would have had: it is never delivered
    run_key TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    PRIMARY KEY (round_id, customer_id, rank)
);

CREATE TABLE IF NOT EXISTS baseline_lists (
    round_id TEXT NOT NULL REFERENCES rounds (round_id),
    method TEXT NOT NULL CHECK (method IN ('b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'chosen_discovery')),
    variant TEXT NOT NULL CHECK (variant IN ('unrestricted', 'new_only')),
    customer_id INTEGER NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    stock_code TEXT NOT NULL,
    run_key TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    PRIMARY KEY (round_id, method, variant, customer_id, rank)
);

CREATE TABLE IF NOT EXISTS round_outcomes (
    round_id TEXT NOT NULL REFERENCES rounds (round_id),
    customer_id INTEGER NOT NULL,
    bought INTEGER NOT NULL CHECK (bought IN (0, 1)),
    products INTEGER NOT NULL CHECK (products >= 0),
    products_in_offer INTEGER NOT NULL CHECK (products_in_offer >= 0),
    spend TEXT NOT NULL,
    days_observed INTEGER NOT NULL CHECK (days_observed BETWEEN 1 AND 7),
    run_key TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    PRIMARY KEY (round_id, customer_id),
    CHECK (products_in_offer <= products AND (bought = 1 OR products = 0))
);

CREATE TABLE IF NOT EXISTS crm_deliveries (
    round_id TEXT NOT NULL REFERENCES rounds (round_id),
    batch INTEGER NOT NULL CHECK (batch >= 1),
    contacts INTEGER NOT NULL CHECK (contacts >= 0),
    created INTEGER NOT NULL CHECK (created >= 0),
    unchanged INTEGER NOT NULL CHECK (unchanged >= 0),
    conflicts INTEGER NOT NULL CHECK (conflicts >= 0),
    readback_equal INTEGER NOT NULL CHECK (readback_equal IN (0, 1)),
    seconds REAL NOT NULL CHECK (seconds >= 0),
    run_key TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    PRIMARY KEY (round_id, batch),
    CHECK (created + unchanged + conflicts <= contacts)
);

CREATE TABLE IF NOT EXISTS round_ops (
    round_id TEXT PRIMARY KEY REFERENCES rounds (round_id),
    base INTEGER NOT NULL CHECK (base >= 0),
    offer INTEGER NOT NULL CHECK (offer >= 0),
    control INTEGER NOT NULL CHECK (control >= 0),
    new_assignments INTEGER NOT NULL CHECK (new_assignments >= 0),
    lists INTEGER NOT NULL CHECK (lists >= 0),
    delivered INTEGER NOT NULL CHECK (delivered >= 0),
    fallback_share REAL NOT NULL CHECK (fallback_share BETWEEN 0 AND 1),
    seconds REAL NOT NULL CHECK (seconds >= 0),
    run_key TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    CHECK (offer + control <= base AND delivered <= offer)
);

CREATE TRIGGER IF NOT EXISTS rounds_no_update BEFORE UPDATE ON rounds
BEGIN SELECT RAISE(ABORT, 'rounds es de solo inserción: una ronda armada no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS rounds_no_delete BEFORE DELETE ON rounds
BEGIN SELECT RAISE(ABORT, 'rounds es de solo inserción: una ronda armada no se borra'); END;

CREATE TRIGGER IF NOT EXISTS rounds_no_second_insert BEFORE INSERT ON rounds
WHEN EXISTS (SELECT 1 FROM rounds WHERE round_id = NEW.round_id)
BEGIN SELECT RAISE(ABORT, 'rounds es de solo inserción: esa ronda ya se armó'); END;

CREATE TRIGGER IF NOT EXISTS contact_base_no_update BEFORE UPDATE ON contact_base
BEGIN SELECT RAISE(ABORT, 'contact_base es de solo inserción: la base de una ronda no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS contact_base_no_delete BEFORE DELETE ON contact_base
BEGIN SELECT RAISE(ABORT, 'contact_base es de solo inserción: la base de una ronda no se borra'); END;

CREATE TRIGGER IF NOT EXISTS contact_base_no_second_insert BEFORE INSERT ON contact_base
WHEN EXISTS (SELECT 1 FROM contact_base WHERE round_id = NEW.round_id AND customer_id = NEW.customer_id)
BEGIN SELECT RAISE(ABORT, 'contact_base es de solo inserción: ese cliente ya está en la base de esa ronda'); END;

CREATE TRIGGER IF NOT EXISTS holdout_assignments_no_update BEFORE UPDATE ON holdout_assignments
BEGIN SELECT RAISE(ABORT, 'holdout_assignments es de solo inserción: la asignación de un cliente no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS holdout_assignments_no_delete BEFORE DELETE ON holdout_assignments
BEGIN SELECT RAISE(ABORT, 'holdout_assignments es de solo inserción: la asignación de un cliente no se borra'); END;

CREATE TRIGGER IF NOT EXISTS holdout_assignments_no_second_insert BEFORE INSERT ON holdout_assignments
WHEN EXISTS (SELECT 1 FROM holdout_assignments WHERE customer_id = NEW.customer_id)
BEGIN SELECT RAISE(ABORT, 'holdout_assignments es de solo inserción: ese cliente ya tiene su asignación'); END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_update BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: un modelo registrado no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_delete BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: un modelo registrado no se borra'); END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_second_insert BEFORE INSERT ON model_registry
WHEN EXISTS (SELECT 1 FROM model_registry WHERE round_id = NEW.round_id AND component = NEW.component)
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: ese modelo ya se registró en esa ronda'); END;

CREATE TRIGGER IF NOT EXISTS offer_lists_no_update BEFORE UPDATE ON offer_lists
BEGIN SELECT RAISE(ABORT, 'offer_lists es de solo inserción: una lista emitida no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS offer_lists_no_delete BEFORE DELETE ON offer_lists
BEGIN SELECT RAISE(ABORT, 'offer_lists es de solo inserción: una lista emitida no se borra'); END;

CREATE TRIGGER IF NOT EXISTS offer_lists_no_second_insert BEFORE INSERT ON offer_lists
WHEN EXISTS (SELECT 1 FROM offer_lists WHERE round_id = NEW.round_id AND customer_id = NEW.customer_id AND rank = NEW.rank)
BEGIN SELECT RAISE(ABORT, 'offer_lists es de solo inserción: ese lugar de esa lista ya se emitió'); END;

CREATE TRIGGER IF NOT EXISTS baseline_lists_no_update BEFORE UPDATE ON baseline_lists
BEGIN SELECT RAISE(ABORT, 'baseline_lists es de solo inserción: una lista de una línea base emitida no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS baseline_lists_no_delete BEFORE DELETE ON baseline_lists
BEGIN SELECT RAISE(ABORT, 'baseline_lists es de solo inserción: una lista de una línea base emitida no se borra'); END;

CREATE TRIGGER IF NOT EXISTS baseline_lists_no_second_insert BEFORE INSERT ON baseline_lists
WHEN EXISTS (SELECT 1 FROM baseline_lists WHERE round_id = NEW.round_id AND method = NEW.method AND variant = NEW.variant AND customer_id = NEW.customer_id AND rank = NEW.rank)
BEGIN SELECT RAISE(ABORT, 'baseline_lists es de solo inserción: ese lugar de esa línea base ya se emitió'); END;

CREATE TRIGGER IF NOT EXISTS round_outcomes_no_update BEFORE UPDATE ON round_outcomes
BEGIN SELECT RAISE(ABORT, 'round_outcomes es de solo inserción: un seguimiento escrito no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS round_outcomes_no_delete BEFORE DELETE ON round_outcomes
BEGIN SELECT RAISE(ABORT, 'round_outcomes es de solo inserción: un seguimiento escrito no se borra'); END;

CREATE TRIGGER IF NOT EXISTS round_outcomes_no_second_insert BEFORE INSERT ON round_outcomes
WHEN EXISTS (SELECT 1 FROM round_outcomes WHERE round_id = NEW.round_id AND customer_id = NEW.customer_id)
BEGIN SELECT RAISE(ABORT, 'round_outcomes es de solo inserción: ese seguimiento ya se escribió'); END;

CREATE TRIGGER IF NOT EXISTS crm_deliveries_no_update BEFORE UPDATE ON crm_deliveries
BEGIN SELECT RAISE(ABORT, 'crm_deliveries es de solo inserción: un lote entregado al CRM no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS crm_deliveries_no_delete BEFORE DELETE ON crm_deliveries
BEGIN SELECT RAISE(ABORT, 'crm_deliveries es de solo inserción: un lote entregado al CRM no se borra'); END;

CREATE TRIGGER IF NOT EXISTS crm_deliveries_no_second_insert BEFORE INSERT ON crm_deliveries
WHEN EXISTS (SELECT 1 FROM crm_deliveries WHERE round_id = NEW.round_id AND batch = NEW.batch)
BEGIN SELECT RAISE(ABORT, 'crm_deliveries es de solo inserción: ese lote ya se entregó'); END;

CREATE TRIGGER IF NOT EXISTS round_ops_no_update BEFORE UPDATE ON round_ops
BEGIN SELECT RAISE(ABORT, 'round_ops es de solo inserción: la operación de una ronda no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS round_ops_no_delete BEFORE DELETE ON round_ops
BEGIN SELECT RAISE(ABORT, 'round_ops es de solo inserción: la operación de una ronda no se borra'); END;

CREATE TRIGGER IF NOT EXISTS round_ops_no_second_insert BEFORE INSERT ON round_ops
WHEN EXISTS (SELECT 1 FROM round_ops WHERE round_id = NEW.round_id)
BEGIN SELECT RAISE(ABORT, 'round_ops es de solo inserción: esa ronda ya tiene su operación'); END;
