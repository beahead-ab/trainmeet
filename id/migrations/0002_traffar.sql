-- Träffarna i ID (ID10): en referens med namn, datum och klubb, tills Hubben loggar in med ID
-- (ärende 78) och kopplar sin träff hit. Själva träffen ägs av Hubben (KONTO-09). Rollerna per
-- träff ligger i role_grant med resource_kind 'meet' och träffens id.
CREATE TABLE meet (
    id uuid PRIMARY KEY,
    club_id uuid NOT NULL REFERENCES club (id) ON DELETE CASCADE,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    starts_on date NOT NULL,
    ends_on date NOT NULL CHECK (ends_on >= starts_on AND ends_on - starts_on <= 30),
    created_by uuid REFERENCES person (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX meet_by_club ON meet (club_id, starts_on);
