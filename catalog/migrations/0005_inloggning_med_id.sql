-- Inloggningen med TrainMeet ID (#66, KONTO-27): the owner's id is ID's subject, and the account
-- is made the first time someone logs in (CAT-42).
--
-- A login that has gone to ID and not come back yet. The browser holds the key in a cookie;
-- only its SHA-256 is stored. The row is used once and lives ten minutes.
CREATE TABLE id_login (
    key_hash bytea PRIMARY KEY CHECK (length(key_hash) = 32),
    state text NOT NULL,
    nonce text NOT NULL,
    verifier text NOT NULL,
    next_path text NOT NULL CHECK (length(next_path) BETWEEN 1 AND 500),
    expires_at timestamptz NOT NULL
);

CREATE INDEX id_login_expires ON id_login (expires_at);

-- ID's token is kept with the session only to log out of ID too (KONTO-01), and goes with it.
ALTER TABLE login_session ADD COLUMN id_token text;
