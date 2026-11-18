-- Friläggningen (CAT-18, CAT-127–CAT-129): bildens bakgrund, och det som sparas för att kunna
-- byta den utan att ladda upp bilden igen.
--
-- background is the picture's background (CAT-128). For any other than the original, the photo
-- at display size, cut around the vehicle, is kept under source_key: what a new background is
-- made from. With the original background the display picture is itself that photo, and
-- source_key is null. The mask, the vehicle's outline from the background removal, is kept
-- under mask_key once it has been made, also when the original background is chosen again.
-- Both count in bytes, the owner's storage (CAT-131), and both go to picture_trash with the rest.

ALTER TABLE picture
    ADD COLUMN background text NOT NULL DEFAULT 'original'
        CHECK (background IN ('original', 'white', 'grey', 'transparent', 'rails')),
    ADD COLUMN source_key text UNIQUE,
    ADD COLUMN mask_key text UNIQUE,
    ADD CONSTRAINT picture_kept_photo CHECK ((background = 'original') = (source_key IS NULL)),
    ADD CONSTRAINT picture_kept_mask CHECK (background = 'original' OR mask_key IS NOT NULL);

-- A removed picture's files, now with the kept photo and the mask.
CREATE OR REPLACE FUNCTION picture_to_trash() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO picture_trash (key)
    SELECT DISTINCT k
    FROM unnest(ARRAY[OLD.display_key, OLD.thumb_key, OLD.original_key, OLD.source_key,
                      OLD.mask_key]) AS k
    WHERE k IS NOT NULL
    ON CONFLICT (key) DO UPDATE SET due_at = now();
    RETURN OLD;
END;
$$;

-- A new background swaps the keys in one statement. A key the picture no longer holds goes to
-- picture_trash in the same transaction; a key that moves to another column, such as the
-- display picture that becomes the kept photo, stays.
CREATE FUNCTION picture_keys_to_trash() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO picture_trash (key)
    SELECT DISTINCT k
    FROM unnest(ARRAY[OLD.display_key, OLD.thumb_key, OLD.original_key, OLD.source_key,
                      OLD.mask_key]) AS k
    WHERE k IS NOT NULL
      AND k <> ALL (array_remove(ARRAY[NEW.display_key, NEW.thumb_key, NEW.original_key,
                                       NEW.source_key, NEW.mask_key], NULL))
    ON CONFLICT (key) DO UPDATE SET due_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER picture_keys_changed
    AFTER UPDATE OF display_key, thumb_key, original_key, source_key, mask_key ON picture
    FOR EACH ROW EXECUTE FUNCTION picture_keys_to_trash();
