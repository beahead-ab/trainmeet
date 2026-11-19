-- Grunden (#89 del a): the people CAD knows, and the login sessions.
--
-- A person's id is TrainMeet ID's subject (the trial login's fixed accounts in the browser test).
-- CAD keeps the name to show in the history, never an address.

CREATE TABLE person (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Only a hash of the session key is stored, so a copy of the database logs no one in. ID's token
-- is kept with the session only to log out of ID too (KONTO-01), and goes with it.
CREATE TABLE login_session (
    key_hash bytea PRIMARY KEY CHECK (length(key_hash) = 32),
    person_id uuid NOT NULL REFERENCES person (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    id_token text
);

CREATE INDEX login_session_person ON login_session (person_id);
CREATE INDEX login_session_expires ON login_session (expires_at);

-- A login that has gone to ID and not come back yet. The browser holds the key in a cookie; only
-- its SHA-256 is stored. The row is used once and lives ten minutes.
CREATE TABLE id_login (
    key_hash bytea PRIMARY KEY CHECK (length(key_hash) = 32),
    state text NOT NULL,
    nonce text NOT NULL,
    verifier text NOT NULL,
    next_path text NOT NULL CHECK (length(next_path) BETWEEN 1 AND 500),
    expires_at timestamptz NOT NULL
);

CREATE INDEX id_login_expires ON id_login (expires_at);
