-- ID:s API (#67): personerna, klubbarna, rollerna per resurs och inbjudningarna. Kontona och
-- inloggningen finns i Keycloak (#66); här finns bara det ID äger utöver dem (KONTO-08).

-- The people ID's API has seen log in: the account's id (Keycloak's sub), the name and the
-- verified address, kept up to date at every login. The address is only shown to its owner.
CREATE TABLE person (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    email text NOT NULL CHECK (email = lower(email) AND length(email) BETWEEN 3 AND 254),
    seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX person_by_email ON person (email);

CREATE TABLE club (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    created_by uuid NOT NULL REFERENCES person (id),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- A role always applies to one resource (KONTO-03): a club's members are roles on the club.
-- The resource is only a reference; the meet, the fleet or the station stays in its app.
CREATE TABLE role_grant (
    id uuid PRIMARY KEY,
    person_id uuid NOT NULL REFERENCES person (id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('admin', 'member', 'organizer', 'reader', 'dispatcher',
        'loco_lead', 'remote_clearer', 'reviewer', 'viewer', 'editor')),
    resource_kind text NOT NULL
        CHECK (resource_kind IN ('club', 'fleet', 'meet', 'station', 'module', 'hub', 'catalog')),
    resource_id text NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 80),
    granted_by uuid REFERENCES person (id) ON DELETE SET NULL,
    at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (person_id, role, resource_kind, resource_id)
);

CREATE INDEX role_grant_by_resource ON role_grant (resource_kind, resource_id);

-- An invitation gives nothing until the person it was sent to says yes (KONTO-29, KONTO-35).
-- Only one invitation waits for the same address and resource at a time.
CREATE TABLE invitation (
    id uuid PRIMARY KEY,
    resource_kind text NOT NULL,
    resource_id text NOT NULL,
    role text NOT NULL,
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
    email text NOT NULL CHECK (email = lower(email) AND length(email) BETWEEN 3 AND 254),
    sent_by uuid NOT NULL REFERENCES person (id) ON DELETE CASCADE,
    state text NOT NULL DEFAULT 'waiting' CHECK (state IN ('waiting', 'accepted', 'declined')),
    at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz
);

CREATE UNIQUE INDEX invitation_waiting ON invitation (resource_kind, resource_id, email)
    WHERE state = 'waiting';
CREATE INDEX invitation_by_email ON invitation (email) WHERE state = 'waiting';

-- The web app's login sessions, as Catalog's: only the key's SHA-256 is stored, and ID's token
-- only to log out of ID too.
CREATE TABLE login_session (
    key_hash bytea PRIMARY KEY CHECK (length(key_hash) = 32),
    person_id uuid NOT NULL REFERENCES person (id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    id_token text
);

CREATE INDEX login_session_expires ON login_session (expires_at);

-- A login that has gone to Keycloak and not come back yet, used once within ten minutes.
CREATE TABLE login_attempt (
    key_hash bytea PRIMARY KEY CHECK (length(key_hash) = 32),
    state text NOT NULL,
    nonce text NOT NULL,
    verifier text NOT NULL,
    next_path text NOT NULL CHECK (length(next_path) BETWEEN 1 AND 500),
    expires_at timestamptz NOT NULL
);
