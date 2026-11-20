-- Foto och kontroll (#89 del c1): the photo chain's jobs, the files they keep, the AI's
-- transcripts, the consent, and the module's Spara original and training opt-in.
--
-- A job is one run of the chain on a module's photos (cad/photos.py). Its key holds the photos'
-- checksums, the profile, the owner's input and the versions, so the same job is never computed
-- or paid twice. What stage 2 measured is kept with it (measured), so the owner's answers make a
-- new version without measuring again.

ALTER TABLE module ADD COLUMN keep_original boolean NOT NULL DEFAULT false;
-- Training TrainMeet's track model on the module's measuring image and geometry (CAD7, CAD-32):
-- the owner's yes and when; null is no. Nothing trains yet.
ALTER TABLE module ADD COLUMN training_at timestamptz;

ALTER TABLE module_event DROP CONSTRAINT module_event_kind_check;
ALTER TABLE module_event ADD CONSTRAINT module_event_kind_check
    CHECK (kind IN ('created', 'saved', 'approved', 'visibility', 'removed', 'photo'));

CREATE TABLE photo_job (
    id uuid PRIMARY KEY,
    module_id uuid NOT NULL REFERENCES module (id) ON DELETE CASCADE,
    -- The module's owner pays and stores: a person or a club (CAD-19, TOKEN-29).
    owner_kind text NOT NULL CHECK (owner_kind IN ('person', 'club')),
    owner_id uuid NOT NULL,
    person_id uuid NOT NULL,
    person_name text NOT NULL,
    key text NOT NULL CHECK (key ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('corners', 'queued', 'running', 'done', 'failed')),
    progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    step text NOT NULL DEFAULT '',
    start jsonb NOT NULL,
    setup jsonb,
    measured jsonb,
    ai jsonb,
    answers jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb,
    chain text NOT NULL,
    reservation uuid,
    cost integer NOT NULL DEFAULT 0 CHECK (cost >= 0),
    -- This measuring image's 12 tokens are drawn: follow-up questions cost nothing (CAD3).
    paid boolean NOT NULL DEFAULT false,
    model text,
    version integer,
    message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX photo_job_module ON photo_job (module_id, created_at DESC);
CREATE INDEX photo_job_waiting ON photo_job (created_at) WHERE state IN ('queued', 'running');
CREATE INDEX photo_job_key ON photo_job (module_id, key) WHERE state = 'done';

-- The files a job keeps, in CAD's bucket or on its disk. counted: in the owner's 100 MB
-- (CAD-19). until: an original's last day, at most 30 days, unless the owner keeps it (CAD4).
CREATE TABLE photo_file (
    key text PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES photo_job (id) ON DELETE CASCADE,
    owner_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('original', 'preview', 'measure', 'display', 'sheet', 'closeup')),
    position integer NOT NULL DEFAULT 0,
    bytes integer NOT NULL CHECK (bytes >= 0),
    width integer,
    height integer,
    counted boolean NOT NULL,
    until timestamptz,
    sha256 text,
    created_at timestamptz NOT NULL DEFAULT now(),
    removed_at timestamptz
);

CREATE INDEX photo_file_owner ON photo_file (owner_id) WHERE removed_at IS NULL;
CREATE INDEX photo_file_job ON photo_file (job_id, kind, position);
CREATE INDEX photo_file_until ON photo_file (until) WHERE removed_at IS NULL;

-- The AI's answers, per (picture's checksum, question version, model): the same question is
-- never asked again (bildkedjan, Reproducerbarhet).
CREATE TABLE photo_transcript (
    checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    question text NOT NULL,
    model text NOT NULL,
    answer text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (checksum, question, model)
);

-- Integritetshändelser: the person's yes to sending a photo to AI, once per version of the text,
-- as Catalog's (CAT-142).
CREATE TABLE privacy_event (
    person_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('ai_photo_consent')),
    version text NOT NULL CHECK (length(version) BETWEEN 1 AND 40),
    at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (person_id, kind, version)
);
