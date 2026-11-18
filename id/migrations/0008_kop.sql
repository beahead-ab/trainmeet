-- Köp av tokens (#79, TOKEN-02, TOKEN-11): ett paket betalas med kort i Stripe Checkout, och
-- de köpta tokens kommer en gång, när Stripe säger att betalningen är klar.
CREATE TABLE token_purchase (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES token_account (id) ON DELETE CASCADE,
    person_id uuid REFERENCES person (id) ON DELETE SET NULL,
    tokens integer NOT NULL CHECK (tokens IN (500, 1500, 5000)),
    price_sek integer NOT NULL CHECK (price_sek > 0),
    mode text NOT NULL CHECK (mode IN ('test', 'live')),
    stripe_session text UNIQUE,
    state text NOT NULL DEFAULT 'started' CHECK (state IN ('started', 'paid')),
    at timestamptz NOT NULL DEFAULT now(),
    paid_at timestamptz
);
