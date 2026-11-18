-- Resan till träffen (#55, CAT-174–CAT-183): ägarens egna träffar, packlistan och bockarna.
--
-- A meet in Catalog is the owner's own list with a name and a date, as long as the link to the
-- Hub waits (CAT-174, K7). template_of is the meet whose pack list it started from (CAT-183).
-- archived_at is set by the tick that brings the last vehicle home once the date has come, or
-- by the owner when nothing on the list is away. An archived meet does not change.
CREATE TABLE meet (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    date date NOT NULL,
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    template_of uuid REFERENCES meet (id) ON DELETE SET NULL
);

CREATE INDEX meet_by_owner ON meet (owner_id, date);

-- The pack list: the vehicles that go to the meet (CAT-175).
CREATE TABLE meet_vehicle (
    meet_id uuid NOT NULL REFERENCES meet (id) ON DELETE CASCADE,
    vehicle_id uuid NOT NULL REFERENCES vehicle (id) ON DELETE CASCADE,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (meet_id, vehicle_id)
);

CREATE INDEX meet_vehicle_by_vehicle ON meet_vehicle (vehicle_id);

-- A bock: one per vehicle and step, with its time, set by a tap or a press on the row
-- (CAT-176). The key makes a double tap one tick, and the first time stands. Taking a vehicle
-- off the pack list takes its ticks with it.
CREATE TABLE meet_tick (
    meet_id uuid NOT NULL,
    vehicle_id uuid NOT NULL,
    step text NOT NULL CHECK (step IN ('pack', 'arrive', 'home')),
    at timestamptz NOT NULL DEFAULT now(),
    by text NOT NULL CHECK (by IN ('tap', 'press')),
    PRIMARY KEY (meet_id, vehicle_id, step),
    FOREIGN KEY (meet_id, vehicle_id) REFERENCES meet_vehicle (meet_id, vehicle_id)
        ON DELETE CASCADE
);

CREATE INDEX meet_tick_by_vehicle ON meet_tick (vehicle_id);

-- The event says which meet's trip moved the vehicle (vehicle, state, time and meet, in the
-- definition's Läget). The name is kept as it was, like the place's (CAT-77, CAT-182).
ALTER TABLE vehicle_event ADD COLUMN meet_name text;
