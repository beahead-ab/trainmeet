-- Avläsningen (#52, CAT-142–CAT-146): ett foto som AI:n läser av, och samtycket till det.
--
-- A reading is a record of its own, apart from the vehicle (CAT-143): it makes no vehicle and
-- keeps no picture, only the hash of what was read. The id comes from the client (CAT-144), so
-- the same reading asked again is answered from here, without reading or drawing again. basis
-- is the SHA-256 over the fleet, the vehicle and its version, if any, and the cleaned photos:
-- the same id with other photos is refused. owner_id is the fleet's owner, whose balance pays;
-- person_id is the one who reads, the owner or a club's administrator. reservation is the
-- reservation in TrainMeet ID, given back when the reading fails or its answer is not used
-- (CAT-20, CAT-145). expires_at is when a reading that never finished is given up and its
-- reservation given back. result is the Reading the person got, only when done.
--
-- One pending reading per person (CAT-146) is kept by the code under the person's lock, and by
-- the database too.

CREATE TABLE reading (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    person_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    kind text NOT NULL CONSTRAINT reading_kind CHECK (kind IN ('image')),
    basis text NOT NULL CHECK (basis ~ '^[0-9a-f]{64}$'),
    pictures integer NOT NULL CHECK (pictures BETWEEN 1 AND 4),
    vehicle_id uuid,
    vehicle_version integer CHECK (vehicle_version >= 1),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'failed', 'discarded')),
    month text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    reservation uuid,
    expires_at timestamptz NOT NULL,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((vehicle_id IS NULL) = (vehicle_version IS NULL)),
    CHECK ((status = 'done') = (result IS NOT NULL))
);

CREATE INDEX reading_by_person ON reading (person_id, created_at);
CREATE UNIQUE INDEX reading_one_pending ON reading (person_id) WHERE status = 'pending';

-- Integritetshändelser (CAT-142): the person's consent, kept once per version of what was shown.
CREATE TABLE privacy_event (
    person_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('ai_reading_consent')),
    version text NOT NULL CHECK (length(version) BETWEEN 1 AND 40),
    at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (person_id, kind, version)
);
