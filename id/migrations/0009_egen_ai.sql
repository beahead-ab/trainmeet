-- Egen AI på kontot (#79, TOKEN-03, TK4): en persons eller klubbs egen AI-tjänst. Nyckeln är
-- förseglad med en nyckel som härleds ur ID:s egen klienthemlighet, så att en kopia av databasen
-- inte räcker för att läsa den.
CREATE TABLE own_ai (
    account_id uuid PRIMARY KEY REFERENCES token_account (id) ON DELETE CASCADE,
    format text NOT NULL CHECK (format IN ('chat', 'claude')),
    address text NOT NULL CHECK (length(address) BETWEEN 8 AND 300),
    model text NOT NULL CHECK (length(model) BETWEEN 1 AND 120),
    key_sealed bytea NOT NULL,
    checked_at timestamptz
);

-- Med egen AI på kontot reserverar en app ingenting: mätaren läser med den och drar inget.
ALTER TABLE token_reservation DROP CONSTRAINT token_reservation_amount_check;
ALTER TABLE token_reservation ADD CONSTRAINT token_reservation_amount_check CHECK (amount >= 0);
