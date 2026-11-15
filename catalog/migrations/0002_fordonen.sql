-- Fordonen (#50): kärnfälten, var fordonet är, platserna hemma, händelserna och ägarhistoriken.
--
-- The number is text exactly as painted (CAT-55); the EVN is derived and never stored (CAT-58).
-- A vehicle is a draft or ready, and ready needs a kind and a litt or a number (CAT-62).
-- Every change raises the version (CAT-63). Writes lock the owner's row first (CAT-40).

-- A named place at home: a box or a shelf (CAT-71). Removing it leaves its vehicles at home
-- without a place.
CREATE TABLE place (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_id, name)
);

CREATE TABLE vehicle (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ready')),
    kind text CHECK (
        kind IN ('locomotive', 'freight_wagon', 'passenger_coach', 'multiple_unit', 'other')
    ),
    litt text NOT NULL DEFAULT '',
    number text NOT NULL DEFAULT '',
    operator text NOT NULL DEFAULT '',
    epoch text NOT NULL DEFAULT '',
    scale text NOT NULL DEFAULT '',
    maker text NOT NULL DEFAULT '',
    article_number text NOT NULL DEFAULT '',
    note text NOT NULL DEFAULT '',
    dcc_address text NOT NULL DEFAULT '',
    functions jsonb NOT NULL DEFAULT '[]',
    -- Where it is now (CAT-70). The place is its home place, also while it is away.
    state text NOT NULL DEFAULT 'home' CHECK (state IN ('home', 'packed', 'at_meet', 'lent')),
    place_id uuid REFERENCES place (id) ON DELETE SET NULL,
    lent_to text,
    lent_since timestamptz,
    lent_until date,
    field_sources jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status = 'draft' OR (kind IS NOT NULL AND (litt <> '' OR number <> ''))),
    CHECK ((state = 'lent') = (lent_to IS NOT NULL AND lent_since IS NOT NULL)),
    CHECK (state <> 'lent' OR status = 'ready')
);

CREATE INDEX vehicle_by_owner ON vehicle (owner_id, created_at);
CREATE INDEX vehicle_by_place ON vehicle (place_id);

-- Every change of state or place, with its time. The owner's own (CAT-77). The place's name is
-- kept as it was, so a renamed or removed place does not change the history.
CREATE TABLE vehicle_event (
    id bigserial PRIMARY KEY,
    vehicle_id uuid NOT NULL REFERENCES vehicle (id) ON DELETE CASCADE,
    at timestamptz NOT NULL DEFAULT now(),
    state text NOT NULL,
    place_name text,
    lent_to text
);

CREATE INDEX vehicle_event_by_vehicle ON vehicle_event (vehicle_id, at);

-- Who has owned the vehicle, from and to (CAT-69).
CREATE TABLE vehicle_owner (
    vehicle_id uuid NOT NULL REFERENCES vehicle (id) ON DELETE CASCADE,
    owner_id uuid NOT NULL,
    since timestamptz NOT NULL DEFAULT now(),
    until timestamptz,
    PRIMARY KEY (vehicle_id, since)
);
