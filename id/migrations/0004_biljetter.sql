-- Biljetten för inloggning på Pi:n utan internet (KONTO-11, KONTO-37, #78): ID skriver under
-- biljetten med en nyckel som bara finns här, och visar den publika delen öppet så att Pi:n kan
-- kontrollera biljetten utan internet. Den senaste nyckeln skriver under; de äldre visas kvar.
CREATE TABLE ticket_key (
    kid text PRIMARY KEY,
    private_pem text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
