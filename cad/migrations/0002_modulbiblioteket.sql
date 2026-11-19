-- Modulbiblioteket (#89 del a): the modules with their versions and history, and the own gable
-- profiles. The norms' and the general profiles are fixed by the norm and live in the code
-- (cad/profiles.py).
--
-- A module belongs to a person or a club in TrainMeet ID (CAD-21). Every save is a new row in
-- module_version, never a change to one (CAD-08). A removed module keeps its rows and history;
-- it is only no longer seen.

CREATE TABLE module (
    id uuid PRIMARY KEY,
    owner_kind text NOT NULL CHECK (owner_kind IN ('person', 'club')),
    owner_id uuid NOT NULL,
    owner_name text NOT NULL CHECK (length(owner_name) BETWEEN 1 AND 80),
    number integer NOT NULL CHECK (number >= 1),
    visibility text NOT NULL CHECK (visibility IN ('me', 'club', 'all')),
    -- The club that sees the module with the visibility klubben.
    club_id uuid,
    club_name text,
    latest integer NOT NULL CHECK (latest >= 1),
    approved_version integer CHECK (approved_version BETWEEN 1 AND latest),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL,
    removed_at timestamptz,
    UNIQUE (owner_id, number),
    CHECK (visibility <> 'club' OR club_id IS NOT NULL)
);

CREATE INDEX module_owner ON module (owner_id) WHERE removed_at IS NULL;
CREATE INDEX module_club ON module (club_id) WHERE removed_at IS NULL;
CREATE INDEX module_for_all ON module (visibility) WHERE removed_at IS NULL;

CREATE TABLE module_version (
    module_id uuid NOT NULL REFERENCES module (id) ON DELETE CASCADE,
    version integer NOT NULL CHECK (version >= 1),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    scale text NOT NULL CHECK (scale IN ('H0', 'N', '0')),
    shape jsonb NOT NULL,
    gables jsonb NOT NULL,
    graph jsonb NOT NULL,
    track_length double precision NOT NULL CHECK (track_length >= 0),
    saved_at timestamptz NOT NULL DEFAULT now(),
    saved_by uuid NOT NULL,
    saved_by_name text NOT NULL,
    approved_at timestamptz,
    approved_by_name text,
    PRIMARY KEY (module_id, version)
);

CREATE TABLE module_event (
    id bigserial PRIMARY KEY,
    module_id uuid NOT NULL REFERENCES module (id) ON DELETE CASCADE,
    at timestamptz NOT NULL DEFAULT now(),
    kind text NOT NULL CHECK (kind IN ('created', 'saved', 'approved', 'visibility', 'removed')),
    version integer NOT NULL CHECK (version >= 1),
    by_name text NOT NULL,
    text text NOT NULL
);

CREATE INDEX module_event_module ON module_event (module_id, at DESC, id DESC);

-- Own gable profiles, a person's or a club's (CAD-07). A club's can be the club's own norm.
CREATE TABLE gable_profile (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
    owner_kind text NOT NULL CHECK (owner_kind IN ('person', 'club')),
    owner_id uuid NOT NULL,
    owner_name text NOT NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    scale text NOT NULL CHECK (scale IN ('H0', 'N', '0')),
    norm text,
    positions jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL
);

CREATE INDEX gable_profile_owner ON gable_profile (owner_id);
