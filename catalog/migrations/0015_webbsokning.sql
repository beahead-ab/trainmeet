-- Webbsökningen (#53 del b, CAT-166–CAT-172, CAT-219, C40).
--
-- A web search is a reading record of its own kind (CAT-143, docs/trainmeet-catalog.md,
-- Avläsningen): the id from the client (CAT-144), the person, the basis, the status, the month
-- and when the reservation is given up, as for a photo. It has no pictures: basis is the
-- SHA-256 over the marking that was searched, the litt, the operator, the kind and the field
-- profile. owner_id is the person, whose own balance pays. result is the PrototypeSearch the
-- person got: the values with valid evidence, and what was dropped.
ALTER TABLE reading
    DROP CONSTRAINT reading_kind,
    ADD CONSTRAINT reading_kind CHECK (kind IN ('image', 'web_search')),
    DROP CONSTRAINT reading_pictures_check,
    ADD CONSTRAINT reading_pictures_check CHECK (
        (kind = 'image' AND pictures BETWEEN 1 AND 4) OR (kind = 'web_search' AND pictures = 0)
    );

-- The proposal a search was sent as (CAT-171): a search is sent once, and one proposal comes
-- from at most one search. When that proposal is approved, the search's 24 tokens come back
-- (CAT-172): refunded_at is when TrainMeet ID said they had. A rejected proposal leaves it
-- empty for good.
ALTER TABLE reading
    ADD COLUMN revision_id uuid REFERENCES prototype_revision (id),
    ADD COLUMN refunded_at timestamptz,
    ADD CHECK (revision_id IS NULL OR kind = 'web_search'),
    ADD CHECK (refunded_at IS NULL OR revision_id IS NOT NULL);

CREATE UNIQUE INDEX reading_by_revision ON reading (revision_id) WHERE revision_id IS NOT NULL;

-- Belägget (CAT-169): per field, the sources whose excerpt held the value when it was searched:
-- the value, the address, the title, the excerpt and when. The publisher's class is not kept:
-- it is read from the reviewed list when the evidence is shown (CAT-168), and so is whether the
-- excerpt still holds the value that stands in the field (CAT-170). A change of a prototype
-- takes the evidence of the fields it keeps with it.
ALTER TABLE prototype_revision
    ADD COLUMN evidence jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(evidence) = 'object');

-- The consent to the web search is a privacy event of its own (CAT-142): what is sent, and to
-- whom, is not the same as for a photo.
ALTER TABLE privacy_event
    DROP CONSTRAINT privacy_event_kind_check,
    ADD CONSTRAINT privacy_event_kind_check
        CHECK (kind IN ('ai_reading_consent', 'web_search_consent'));
