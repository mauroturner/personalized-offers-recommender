-- What came in and what the runs did (plan, section 5; decisions D22, D24): the deliveries, the runs, the validation of each run, the lines and the products.
-- ``deliveries`` and ``pipeline_runs`` are updated by the flow (a run is ``running`` until ``report`` closes it; a delivery that was rejected is loaded over its row once it is
-- right); ``validation_results``, ``lines`` and ``products`` are insert-only (three triggers each, the same that every table of 002_flow.sql has): what a validation said, what
-- was received and what a product was when it was first seen cannot be rewritten afterwards. Instants are text 'YYYY-MM-DD HH:MM:SS' and days 'YYYY-MM-DD'. A price is the
-- decimal text of the number that the source gave, with every digit it had (never a floating point that was rounded on the way).

CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('launch', 'weekly', 'close')),
    first_day TEXT NOT NULL,
    last_day TEXT NOT NULL,
    as_of TEXT NOT NULL,
    rows INTEGER NOT NULL CHECK (rows >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('published', 'loaded', 'rejected')),
    run_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_key TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed', 'rejected', 'no_delivery')),
    delivery_id TEXT REFERENCES deliveries (delivery_id),
    as_of TEXT,
    config_sha256 TEXT CHECK (config_sha256 IS NULL OR length(config_sha256) = 64),
    round_id TEXT,
    peak_working_set_mb REAL,
    memory_counter TEXT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS validation_results (
    run_key TEXT NOT NULL REFERENCES pipeline_runs (run_key),
    rule_id TEXT NOT NULL,
    name_es TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('bloqueante', 'advertencia', 'informativa')),
    scope TEXT NOT NULL,
    aggregation TEXT NOT NULL CHECK (aggregation IN ('source', 'per_run', 'latest')),
    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
    rows_affected INTEGER NOT NULL CHECK (rows_affected >= 0),
    examples_json TEXT NOT NULL CHECK (json_valid(examples_json)),   -- the keys of the lines, never a customer number
    PRIMARY KEY (run_key, rule_id)
);

CREATE TABLE IF NOT EXISTS lines (
    line_key INTEGER PRIMARY KEY,                                    -- the sheet times 10 million plus its row (D03)
    delivery_id TEXT NOT NULL REFERENCES deliveries (delivery_id),
    invoice TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    description TEXT,
    quantity INTEGER NOT NULL,
    invoice_date TEXT NOT NULL,
    price TEXT NOT NULL,
    customer_id INTEGER,
    country TEXT NOT NULL,
    internal_repeat INTEGER NOT NULL CHECK (internal_repeat IN (0, 1)),
    role TEXT NOT NULL CHECK (role IN ('cancellation', 'adjustment', 'non_product', 'bad_price', 'guest_purchase', 'purchase'))
);

CREATE INDEX IF NOT EXISTS lines_by_delivery ON lines (delivery_id);

CREATE TABLE IF NOT EXISTS products (
    stock_code TEXT PRIMARY KEY,
    description_es TEXT,                                             -- the commonest description the source gave it in the delivery where it was first seen
    first_seen TEXT NOT NULL,
    launch_invoices INTEGER NOT NULL CHECK (launch_invoices >= 0)    -- invoices of the launch history with the product (0 for a product first seen later)
);

CREATE TRIGGER IF NOT EXISTS validation_results_no_update BEFORE UPDATE ON validation_results
BEGIN SELECT RAISE(ABORT, 'validation_results es de solo inserción: lo que una validación dijo no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS validation_results_no_delete BEFORE DELETE ON validation_results
BEGIN SELECT RAISE(ABORT, 'validation_results es de solo inserción: lo que una validación dijo no se borra'); END;

CREATE TRIGGER IF NOT EXISTS validation_results_no_second_insert BEFORE INSERT ON validation_results
WHEN EXISTS (SELECT 1 FROM validation_results WHERE run_key = NEW.run_key AND rule_id = NEW.rule_id)
BEGIN SELECT RAISE(ABORT, 'validation_results es de solo inserción: esa regla ya se informó en la corrida'); END;

CREATE TRIGGER IF NOT EXISTS lines_no_update BEFORE UPDATE ON lines
BEGIN SELECT RAISE(ABORT, 'lines es de solo inserción: una línea recibida no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS lines_no_delete BEFORE DELETE ON lines
BEGIN SELECT RAISE(ABORT, 'lines es de solo inserción: una línea recibida no se borra'); END;

CREATE TRIGGER IF NOT EXISTS lines_no_second_insert BEFORE INSERT ON lines
WHEN EXISTS (SELECT 1 FROM lines WHERE line_key = NEW.line_key)
BEGIN SELECT RAISE(ABORT, 'lines es de solo inserción: esa línea ya se recibió'); END;

CREATE TRIGGER IF NOT EXISTS products_no_update BEFORE UPDATE ON products
BEGIN SELECT RAISE(ABORT, 'products es de solo inserción: un producto visto no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS products_no_delete BEFORE DELETE ON products
BEGIN SELECT RAISE(ABORT, 'products es de solo inserción: un producto visto no se borra'); END;

CREATE TRIGGER IF NOT EXISTS products_no_second_insert BEFORE INSERT ON products
WHEN EXISTS (SELECT 1 FROM products WHERE stock_code = NEW.stock_code)
BEGIN SELECT RAISE(ABORT, 'products es de solo inserción: ese producto ya se vio'); END;
