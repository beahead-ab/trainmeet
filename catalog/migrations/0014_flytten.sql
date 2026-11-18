-- Flytten från gamla TrainCatalog (#57, CAT-204–CAT-207): de gamla fälten, väntande vagnparker
-- och vad som redan är flyttat.
--
-- legacy holds an old vehicle's values that are not core fields, by the old field's Swedish
-- label, so nothing is lost (CAT-205). Only the move writes it; the owner reads it on the card.
--
-- An old owner's fleet waits under an owner of its own until the person logs in with TrainMeet
-- ID (CAT-204). waiting_fleet keeps a keyed hash of the old verified e-mail address, HMAC-SHA256
-- with a pepper that only the environment has (catalog/waiting.py), never the address itself.
-- The first login whose verified e-mail gives the same hash takes the fleet over in one
-- transaction, and the row goes with the waiting owner.
--
-- flytt_map says what has been moved: the kind, the old id and the new id. A second run moves
-- nothing twice, and a later run adds only what is new (catalog/flytten.py). When a waiting
-- fleet is taken over, its owner's row points to the person instead.

ALTER TABLE vehicle ADD COLUMN legacy jsonb NOT NULL DEFAULT '{}'
    CHECK (jsonb_typeof(legacy) = 'object');

CREATE TABLE waiting_fleet (
    owner_id uuid PRIMARY KEY REFERENCES owner (id) ON DELETE CASCADE,
    email_hash bytea NOT NULL UNIQUE CHECK (length(email_hash) = 32),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE flytt_map (
    kind text NOT NULL
        CHECK (kind IN ('owner', 'vehicle', 'picture', 'tag', 'assignment', 'event')),
    old_id text NOT NULL CHECK (length(old_id) BETWEEN 1 AND 64),
    new_id text NOT NULL CHECK (length(new_id) BETWEEN 1 AND 64),
    moved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, old_id)
);

CREATE INDEX flytt_map_owner ON flytt_map (new_id) WHERE kind = 'owner';
