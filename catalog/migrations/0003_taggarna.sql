-- Taggarna (#54): taggen, dess identifierare, kopplingen till fordonet och tagghändelserna,
-- och uppslagens räknare. Gamla TrainCatalogs taggmodell med databasvillkoren (C14).

-- The owner shows their name when someone else taps their vehicles. Off from the start (CAT-101).
ALTER TABLE owner ADD COLUMN show_name boolean NOT NULL DEFAULT false;

-- A tag: an NFC tag, a QR label or a simulated tag, with an owner and a name (CAT-78).
CREATE TABLE tag (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    kind text NOT NULL CHECK (kind IN ('nfc', 'qr', 'sim')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- A tag's identifiers. (namespace, value) is unique in all of Catalog (CAT-78, CAT-79).
CREATE TABLE tag_identifier (
    namespace text NOT NULL CHECK (namespace IN ('iso14443a_uid', 'qr', 'sim')),
    value text NOT NULL,
    tag_id uuid NOT NULL REFERENCES tag (id) ON DELETE CASCADE,
    PRIMARY KEY (namespace, value),
    CHECK (namespace <> 'iso14443a_uid' OR value ~ '^([0-9a-f]{2}){4,16}$')
);

CREATE INDEX tag_identifier_by_tag ON tag_identifier (tag_id);

-- A tag on a vehicle, from start to end (CAT-81). The slot is nfc for NFC and simulated tags,
-- and qr for QR labels: a vehicle has at most one active of each (CAT-82).
CREATE TABLE tag_assignment (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    tag_id uuid NOT NULL REFERENCES tag (id) ON DELETE CASCADE,
    vehicle_id uuid NOT NULL REFERENCES vehicle (id) ON DELETE CASCADE,
    slot text NOT NULL CHECK (slot IN ('nfc', 'qr')),
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE UNIQUE INDEX tag_assignment_one_active_per_tag ON tag_assignment (tag_id)
    WHERE ended_at IS NULL;
CREATE UNIQUE INDEX tag_assignment_one_active_per_slot ON tag_assignment (vehicle_id, slot)
    WHERE ended_at IS NULL;

-- Every link and unlink, with who and when. Only the one who did it sees it (CAT-93).
CREATE TABLE tag_event (
    id bigserial PRIMARY KEY,
    tag_id uuid NOT NULL REFERENCES tag (id) ON DELETE CASCADE,
    vehicle_id uuid REFERENCES vehicle (id) ON DELETE SET NULL,
    by_owner uuid NOT NULL,
    event text NOT NULL CHECK (event IN ('linked', 'unlinked')),
    at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX tag_event_by_tag ON tag_event (tag_id, at);

-- One window per person, never which tags were read (CAT-111). Visitors who are not logged in
-- are counted in memory by Catalog, so no address is ever stored (CAT-112).
CREATE TABLE tag_lookup_counter (
    owner_id uuid PRIMARY KEY REFERENCES owner (id) ON DELETE CASCADE,
    window_start timestamptz NOT NULL,
    count integer NOT NULL CHECK (count >= 0)
);

-- Koppla tagg: the vehicle waits for a tag for 10 minutes, and the next unlinked tag the owner
-- taps is offered to it (CAT-94). replace is the link that was seen, when replacing (CAT-88).
CREATE TABLE pending_link (
    owner_id uuid PRIMARY KEY REFERENCES owner (id) ON DELETE CASCADE,
    vehicle_id uuid NOT NULL REFERENCES vehicle (id) ON DELETE CASCADE,
    replace uuid,
    expires_at timestamptz NOT NULL
);
