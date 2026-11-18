-- Förebildskatalogen (#53 del a, CAT-03, CAT-155–CAT-165): förebilderna, deras revisioner och
-- kopplingen från fordonet.
--
-- The catalog is shared by everyone and holds only the type data (CAT-155), as text by the keys
-- of the field register (catalog/prototype_fields.py, CAT-156). A prototype has revisions
-- (CAT-159): every proposal, a new prototype or a change, is a revision of its own, numbered
-- from 1, that waits in the review queue until a reviewer approves or rejects it with a comment
-- (CAT-164). base is the reviewed revision a change was built on. The prototype's status is
-- reviewed once a revision is, and current_revision is then the latest reviewed one, the one
-- everyone sees; before that the prototype is proposed, or rejected with its first proposal.
-- Revisions are never changed once reviewed, and a prototype is never removed.
--
-- created_by and reviewer are owners in Catalog, people who were logged in. A removed account
-- leaves its proposals and reviews without a name (CAT-193).
--
-- A vehicle linked to a prototype keeps the revision and a snapshot of its type data, name,
-- kind and profile (CAT-160), so a new revision never changes it in the background (CAT-161).
-- prototype_overrides are the owner's own values, which the prototype never overwrites
-- (CAT-162).

CREATE TABLE prototype (
    id uuid PRIMARY KEY,
    status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'reviewed', 'rejected')),
    current_revision integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'reviewed') = (current_revision IS NOT NULL))
);

CREATE TABLE prototype_revision (
    id uuid PRIMARY KEY,
    prototype_id uuid NOT NULL REFERENCES prototype (id),
    number integer NOT NULL CHECK (number >= 1),
    base integer CHECK (base >= 1),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    kind text CHECK (
        kind IN ('locomotive', 'freight_wagon', 'passenger_coach', 'multiple_unit', 'other')
    ),
    profile text NOT NULL CHECK (profile IN ('SE', 'EU', 'US')),
    fields jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(fields) = 'object'),
    source_kind text NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 40),
    source text NOT NULL CHECK (length(source) BETWEEN 1 AND 1000),
    created_by uuid REFERENCES owner (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    review text NOT NULL DEFAULT 'proposed' CHECK (review IN ('proposed', 'reviewed', 'rejected')),
    reviewer uuid REFERENCES owner (id) ON DELETE SET NULL,
    comment text NOT NULL DEFAULT '' CHECK (length(comment) <= 1000),
    reviewed_at timestamptz,
    UNIQUE (prototype_id, number),
    CHECK ((review = 'proposed') = (reviewed_at IS NULL)),
    CHECK (review <> 'rejected' OR comment <> '')
);

-- The revision everyone sees is one of the prototype's own, and a reviewed one.
ALTER TABLE prototype ADD FOREIGN KEY (id, current_revision)
    REFERENCES prototype_revision (prototype_id, number) DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX prototype_revision_queue ON prototype_revision (created_at) WHERE review = 'proposed';
CREATE INDEX prototype_revision_by ON prototype_revision (created_by, created_at);

ALTER TABLE vehicle
    ADD COLUMN prototype_id uuid,
    ADD COLUMN prototype_revision integer,
    ADD COLUMN prototype_snapshot jsonb,
    ADD COLUMN prototype_overrides jsonb NOT NULL DEFAULT '{}'
        CHECK (jsonb_typeof(prototype_overrides) = 'object'),
    ADD FOREIGN KEY (prototype_id, prototype_revision)
        REFERENCES prototype_revision (prototype_id, number),
    ADD CHECK (
        (prototype_id IS NULL) = (prototype_revision IS NULL)
        AND (prototype_id IS NULL) = (prototype_snapshot IS NULL)
        AND (prototype_id IS NOT NULL OR prototype_overrides = '{}')
    );

CREATE INDEX vehicle_by_prototype ON vehicle (prototype_id) WHERE prototype_id IS NOT NULL;
