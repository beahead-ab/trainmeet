-- TrainMeet tokens (#79, TOKEN-06, TOKEN-12): saldot per person och per klubb (TK1).
-- Köpta tokens ligger kvar; månadens gratiskvot räknas per månad och sparas inte (TK2).
CREATE TABLE token_account (
    id uuid PRIMARY KEY,
    person_id uuid UNIQUE REFERENCES person (id) ON DELETE CASCADE,
    club_id uuid UNIQUE REFERENCES club (id) ON DELETE CASCADE,
    bought integer NOT NULL DEFAULT 0 CHECK (bought >= 0),
    CHECK ((person_id IS NULL) <> (club_id IS NULL))
);

-- Det som är använt av månadens gratiskvot, i svensk tid. En ny månad börjar på noll.
CREATE TABLE token_month (
    account_id uuid NOT NULL REFERENCES token_account (id) ON DELETE CASCADE,
    month text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    free_used integer NOT NULL DEFAULT 0 CHECK (free_used >= 0),
    PRIMARY KEY (account_id, month)
);

-- En app reserverar före ett arbete som kostar, och drar sedan det som det kostade eller lämnar
-- tillbaka allt (TOKEN-24). Samma nyckel från samma app ger samma reservation (TOKEN-28).
CREATE TABLE token_reservation (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES token_account (id) ON DELETE CASCADE,
    app text NOT NULL CHECK (length(app) BETWEEN 1 AND 40),
    key text NOT NULL CHECK (length(key) BETWEEN 1 AND 120),
    person_id uuid REFERENCES person (id) ON DELETE SET NULL,
    amount integer NOT NULL CHECK (amount > 0),
    month text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    from_free integer NOT NULL CHECK (from_free >= 0),
    from_bought integer NOT NULL CHECK (from_bought >= 0),
    drawn integer NOT NULL DEFAULT 0 CHECK (drawn >= 0),
    state text NOT NULL DEFAULT 'held' CHECK (state IN ('held', 'drawn', 'returned')),
    what text NOT NULL CHECK (length(what) BETWEEN 1 AND 120),
    at timestamptz NOT NULL,
    expires timestamptz NOT NULL,
    settled_at timestamptz,
    UNIQUE (app, key),
    CHECK (from_free + from_bought = amount),
    CHECK (drawn <= amount)
);

CREATE INDEX token_reservation_held ON token_reservation (account_id) WHERE state = 'held';
