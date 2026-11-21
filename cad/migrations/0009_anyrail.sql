-- Import från AnyRail (#91, TKL16, ANYRAIL-01–22): an AnyRail file as the owner uploaded it,
-- kept in CAD only (ANYRAIL-08), with the scale and the measures it is read with (AR5, AR6), so
-- that the owner can read it again with other measures. Only the person who uploaded it sees it.
--
-- The answer of the latest reading is kept as it was given (result), so that the page opens
-- without reading the file again; the exports read it again, and the same file with the same
-- measures always gives the same answer. created holds what Skapa modulerna made: the modules
-- and the assembly. A file goes with its person.

CREATE TABLE anyrail_import (
    id uuid PRIMARY KEY,
    person_id uuid NOT NULL REFERENCES person (id) ON DELETE CASCADE,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    format text NOT NULL CHECK (format IN ('xml', 'any')),
    data bytea NOT NULL CHECK (length(data) BETWEEN 1 AND 20971520),
    sha256 text NOT NULL CHECK (length(sha256) = 64),
    library text,
    scale text NOT NULL CHECK (scale IN ('H0', 'N', '0')),
    measures jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    result jsonb NOT NULL,
    created jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX anyrail_import_person ON anyrail_import (person_id, created_at DESC);
