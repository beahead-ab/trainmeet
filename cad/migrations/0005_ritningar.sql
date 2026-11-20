-- Ladda upp ritning (#89 del c4, CAD6, CAD-31): the profile Stationsritning's jobs, the files
-- they keep, and the yes to sending a raster drawing to AI.
--
-- A job is one drawing taken in for Studio and its read (cad/drawings.py). It belongs to the
-- person who uploaded it, in Studio or in CAD, who also pays for an AI transcription. Its key
-- holds the file's checksum, the page, with or without AI, and the reader's version: the same
-- file and input give the same job, read once and paid once. The AI's transcription of a page
-- is kept as a transcript in photo_transcript, under its own question version, so the same page
-- is never transcribed twice.

CREATE TABLE drawing_job (
    id uuid PRIMARY KEY,
    person_id uuid NOT NULL,
    person_name text NOT NULL,
    -- The drawing as sent: its checksum, the job's file key when it is read.
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    key text NOT NULL CHECK (key ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('waiting', 'queued', 'running', 'done', 'failed')),
    progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    step text NOT NULL DEFAULT '',
    start jsonb NOT NULL,
    setup jsonb,
    words jsonb,
    answers jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb,
    chain text NOT NULL,
    reservation uuid,
    cost integer NOT NULL DEFAULT 0 CHECK (cost >= 0),
    paid boolean NOT NULL DEFAULT false,
    model text,
    message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX drawing_job_person ON drawing_job (person_id, sha256, created_at DESC);
CREATE INDEX drawing_job_waiting ON drawing_job (created_at) WHERE state IN ('queued', 'running');
CREATE INDEX drawing_job_key ON drawing_job (person_id, key) WHERE state = 'done';

-- The drawing as sent and its straightened underlay, in CAD's bucket or on its disk, for at most
-- 30 days: Studio makes its own station model from the read, and keeps no file of CAD's.
CREATE TABLE drawing_file (
    key text PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES drawing_job (id) ON DELETE CASCADE,
    owner_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('original', 'underlay', 'sheet')),
    bytes integer NOT NULL CHECK (bytes >= 0),
    width integer,
    height integer,
    until timestamptz NOT NULL,
    sha256 text,
    created_at timestamptz NOT NULL DEFAULT now(),
    removed_at timestamptz
);

CREATE INDEX drawing_file_job ON drawing_file (job_id, kind);
CREATE INDEX drawing_file_until ON drawing_file (until) WHERE removed_at IS NULL;

ALTER TABLE privacy_event DROP CONSTRAINT privacy_event_kind_check;
ALTER TABLE privacy_event ADD CONSTRAINT privacy_event_kind_check
    CHECK (kind IN ('ai_photo_consent', 'ai_drawing_consent'));
