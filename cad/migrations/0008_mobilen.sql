-- CAD i mobilen (#90, CAD1, CADMOB-12): Fota med mobilen's QR code and the phone's session.
--
-- The one-time code and the phone's session key are shown to the browsers once and never kept:
-- only their SHA-256, so a copy of the database opens no phone flow. The code is used once and
-- lives ten minutes; the phone's session lives two hours from when the code was given, and only
-- reaches the mobile flow (cad/mobile.py). The phone reports its step, module and photo job here
-- so that the computer can follow it. A row goes a day after its session ends.

CREATE TABLE mobile_handoff (
    id uuid PRIMARY KEY,
    code_hash bytea NOT NULL UNIQUE CHECK (length(code_hash) = 32),
    person_id uuid NOT NULL REFERENCES person (id) ON DELETE CASCADE,
    -- From a module's page: the phone reaches only this module.
    bound_id uuid REFERENCES module (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    code_expires_at timestamptz NOT NULL,
    opened_at timestamptz,
    session_hash bytea UNIQUE CHECK (session_hash IS NULL OR length(session_hash) = 32),
    session_expires_at timestamptz,
    ended_at timestamptz,
    step text NOT NULL DEFAULT 'start'
        CHECK (step IN ('start', 'matt', 'gavlar', 'fota', 'kontroll', 'fraga', 'klar')),
    module_id uuid REFERENCES module (id) ON DELETE SET NULL,
    job_id uuid REFERENCES photo_job (id) ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((opened_at IS NULL) = (session_hash IS NULL)),
    CHECK ((session_hash IS NULL) = (session_expires_at IS NULL))
);

CREATE INDEX mobile_handoff_person ON mobile_handoff (person_id, created_at DESC);
CREATE INDEX mobile_handoff_created ON mobile_handoff (created_at);
