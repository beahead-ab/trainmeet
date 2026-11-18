-- Bilderna (CAT-05, CAT-17, CAT-123–CAT-133): flera bilder per fordon, en huvudbild, och
-- lagringen per ägare.
--
-- The files are private in Object Storage (CAT-130); a row holds their keys and what they take
-- together, which counts in the owner's storage (CAT-131). The owner is the fleet's owner, also
-- when someone the fleet is shared with uploads (CAT-133). Writes lock the owner's row first
-- (CAT-40), so two uploads at once never go over the limit.

CREATE TABLE picture (
    id uuid PRIMARY KEY,
    vehicle_id uuid NOT NULL REFERENCES vehicle (id) ON DELETE CASCADE,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    position integer NOT NULL CHECK (position >= 0),
    is_main boolean NOT NULL DEFAULT false,
    -- The display picture's size in pixels.
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    display_key text NOT NULL UNIQUE,
    thumb_key text NOT NULL UNIQUE,
    -- Only with Spara original (CAT-17, CAT-126).
    original_key text UNIQUE,
    bytes bigint NOT NULL CHECK (bytes > 0),
    -- Who uploaded it: the owner, or someone the fleet is shared with. Like the vehicles'
    -- history, a removed person's id is replaced with the zero id (CAT-193).
    uploaded_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- One main picture per vehicle, kept by the database (CAT-125).
CREATE UNIQUE INDEX picture_one_main_per_vehicle ON picture (vehicle_id) WHERE is_main;
CREATE INDEX picture_by_vehicle ON picture (vehicle_id, position);
CREATE INDEX picture_by_owner ON picture (owner_id);

-- Files to delete from the store. A removed picture's keys come here by the trigger, also when
-- the picture goes with its vehicle or its owner, so no file is ever left behind. An upload
-- marks its keys here before it stores them, with a later due time, and takes the marks away
-- in the transaction that saves the picture: an upload that fails or stops halfway leaves
-- marks, and its files are deleted when they are due.
CREATE TABLE picture_trash (
    key text PRIMARY KEY,
    due_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX picture_trash_due ON picture_trash (due_at);

CREATE FUNCTION picture_to_trash() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO picture_trash (key)
    SELECT k FROM unnest(ARRAY[OLD.display_key, OLD.thumb_key, OLD.original_key]) AS k
    WHERE k IS NOT NULL
    ON CONFLICT (key) DO UPDATE SET due_at = now();
    RETURN OLD;
END;
$$;

CREATE TRIGGER picture_removed AFTER DELETE ON picture
    FOR EACH ROW EXECUTE FUNCTION picture_to_trash();
