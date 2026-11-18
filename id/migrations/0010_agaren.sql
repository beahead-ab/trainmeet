-- Ägarsidan (#79, TOKEN-05, TOKEN-18, TK6, TK15): faktorerna, månadens budget och taken per
-- dygn, och vad TrainMeets AI kostar, uppmätt. Startvärdena är Claudes förslag; ägaren ändrar dem.
CREATE TABLE token_settings (
    id integer PRIMARY KEY CHECK (id = 1),
    ai_factor numeric(8, 2) NOT NULL DEFAULT 2,
    storage_factor numeric(8, 2) NOT NULL DEFAULT 10,
    monthly_budget_sek integer NOT NULL DEFAULT 1000 CHECK (monthly_budget_sek >= 0),
    daily_cap_person integer NOT NULL DEFAULT 240 CHECK (daily_cap_person >= 0),
    daily_cap_club integer NOT NULL DEFAULT 1200 CHECK (daily_cap_club >= 0),
    usd_sek numeric(10, 4) NOT NULL DEFAULT 9.7,
    price_in_usd numeric(10, 4) NOT NULL DEFAULT 2,
    price_out_usd numeric(10, 4) NOT NULL DEFAULT 10,
    changed_at timestamptz,
    changed_by uuid REFERENCES person (id) ON DELETE SET NULL
);

INSERT INTO token_settings (id) VALUES (1);

-- Det TrainMeets AI har kostat, per läsning, i svensk månad.
CREATE TABLE meter_usage (
    id bigserial PRIMARY KEY,
    at timestamptz NOT NULL,
    month text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    pages integer NOT NULL CHECK (pages > 0),
    input_tokens integer NOT NULL CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL CHECK (output_tokens >= 0),
    cost_sek numeric(12, 4) NOT NULL CHECK (cost_sek >= 0)
);

CREATE INDEX meter_usage_month ON meter_usage (month);

-- Larmet vid 80 % och stoppet vid 100 % skickas en gång per månad och nivå.
CREATE TABLE budget_alarm (
    month text NOT NULL,
    level integer NOT NULL CHECK (level IN (80, 100)),
    at timestamptz NOT NULL,
    PRIMARY KEY (month, level)
);
