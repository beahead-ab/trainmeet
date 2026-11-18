-- Flera foton i en omgång (#52 del b, CAT-146–CAT-153): omgångarna, deras utkast och kön.
--
-- A batch is up to 30 photos, one per vehicle (CAT-147). The id comes from the client, so the
-- photos may come in several requests. owner_id is the fleet's owner; created_by is the person
-- who left the photos: the owner, a club's administrator, or someone who edits the fleet. Like
-- the pictures' uploaded_by, a removed person's id is replaced with the zero id (CAT-193). ai
-- says that the photos are read with AI; club says, as ID said when the batch was made, whose
-- balance pays: the club's or the person's (TOKEN-29). wait_until is when the queue goes on
-- after the hour's limit or the day's cap (CAT-146), with the message the owner sees.
--
-- Each photo is a card: a draft, not a vehicle (CAT-148). The queue is the cards themselves,
-- waiting in order, so it outlives a restart (CAT-151). sha256 is the hash of the original file
-- as it came, unique per owner, so the same file is never two drafts (CAT-149). values are what
-- the vehicle becomes, version is raised by every change of them, and the suggestions, the
-- question and the warnings are the AI's, from its reading (0010_avlasning.sql, which gets the
-- column batch: a batch's readings have their own limit an hour). Only the photo made anew
-- without metadata is kept (CAT-124), as a display picture and a thumbnail in the pictures'
-- store; they do not count in the storage until approved. Godkänn alla gives the keys to the
-- vehicle's picture, and the card keeps its hash, linked to the vehicle: removing the vehicle
-- removes the card.
--
-- Writes lock the owner's row first (CAT-40). A card's files go to picture_trash when the card
-- goes: removed by itself, with its batch, or with the owner's account.

ALTER TABLE reading ADD COLUMN batch boolean NOT NULL DEFAULT false;

CREATE TABLE batch (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    created_by uuid NOT NULL,
    ai boolean NOT NULL,
    club boolean NOT NULL DEFAULT false,
    wait_until timestamptz,
    wait_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, owner_id),
    CHECK ((wait_until IS NULL) = (wait_message IS NULL))
);

CREATE INDEX batch_by_owner ON batch (owner_id, created_at);

CREATE TABLE batch_card (
    id uuid PRIMARY KEY,
    batch_id uuid NOT NULL,
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    position integer NOT NULL CHECK (position >= 0),
    status text NOT NULL CHECK (
        status IN ('waiting', 'reading', 'ready', 'review', 'failed', 'manual', 'approved')
    ),
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    fields jsonb NOT NULL DEFAULT '{}',
    suggestions jsonb NOT NULL DEFAULT '{}',
    question jsonb,
    warnings jsonb NOT NULL DEFAULT '[]',
    message text NOT NULL DEFAULT '',
    reading_id uuid REFERENCES reading (id) ON DELETE SET NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    -- The display picture's size in pixels, and what it and the thumbnail take.
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    bytes bigint NOT NULL CHECK (bytes > 0),
    display_key text UNIQUE,
    thumb_key text UNIQUE,
    vehicle_id uuid REFERENCES vehicle (id) ON DELETE CASCADE,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (batch_id, owner_id) REFERENCES batch (id, owner_id) ON DELETE CASCADE,
    UNIQUE (batch_id, position),
    UNIQUE (owner_id, sha256),
    CHECK ((status = 'approved') = (vehicle_id IS NOT NULL)),
    CHECK ((status = 'approved') = (approved_at IS NOT NULL)),
    CHECK ((status = 'approved') = (display_key IS NULL)),
    CHECK ((display_key IS NULL) = (thumb_key IS NULL))
);

-- The queue: the cards waiting or being read.
CREATE INDEX batch_card_queue ON batch_card (status) WHERE status IN ('waiting', 'reading');
CREATE INDEX batch_card_by_vehicle ON batch_card (vehicle_id);

-- A removed card's files, also when it goes with its batch or its owner. An approved card's
-- files are the vehicle's picture's, and go with it.
CREATE FUNCTION batch_card_to_trash() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO picture_trash (key)
    SELECT k FROM unnest(ARRAY[OLD.display_key, OLD.thumb_key]) AS k
    WHERE k IS NOT NULL
    ON CONFLICT (key) DO UPDATE SET due_at = now();
    RETURN OLD;
END;
$$;

CREATE TRIGGER batch_card_removed AFTER DELETE ON batch_card
    FOR EACH ROW EXECUTE FUNCTION batch_card_to_trash();
