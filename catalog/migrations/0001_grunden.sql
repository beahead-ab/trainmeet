-- Grunden (#48): the owner's row and the login sessions.
--
-- Every write locks the owner's row first, then vehicle and tag, in a short transaction
-- (CAT-40). The owner is a person, and later a club (C28); the id comes from the login,
-- the trial login until TrainMeet ID (CAT-214).

CREATE TABLE owner (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Only a hash of the session key is stored, so a copy of the database logs no one in.
CREATE TABLE login_session (
    key_hash bytea PRIMARY KEY CHECK (length(key_hash) = 32),
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX login_session_owner ON login_session (owner_id);
CREATE INDEX login_session_expires ON login_session (expires_at);
