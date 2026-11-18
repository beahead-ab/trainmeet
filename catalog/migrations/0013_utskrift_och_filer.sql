-- Utskrift och filer (#56, CAT-184–CAT-188): utkast från filer i Tellurians format.
--
-- An import of files in Tellurian's format (CAT-186) is a batch like the photos' (0011_omgangar.sql),
-- read by no AI: each file is a card, a draft that the owner reviews and approves with Godkänn
-- alla (CAT-150). source says what the cards came from, photos or files: on the batch, and on
-- each card, so that the database keeps a photo's card as strict as before. A file's card has the
-- file's name, and the values the file gave (imported), so that a value approved as the file had
-- it gets the source import (CAT-64). Its picture is the file's model picture, made anew without
-- metadata as a photo is (CAT-124); a file without one gives a card without a picture, and so
-- without its size. The SHA-256 is the file's, as for a photo: the same file is never two drafts
-- (CAT-149).
--
-- The QR labels (CAT-184) and the account export (CAT-188) need nothing new in the database.

ALTER TABLE batch ADD COLUMN source text NOT NULL DEFAULT 'photo'
    CHECK (source IN ('photo', 'file'));
ALTER TABLE batch ADD CONSTRAINT batch_files_without_ai CHECK (source = 'photo' OR NOT ai);

ALTER TABLE batch_card ADD COLUMN source text NOT NULL DEFAULT 'photo'
    CHECK (source IN ('photo', 'file'));
ALTER TABLE batch_card ADD COLUMN file_name text CHECK (length(file_name) BETWEEN 1 AND 120);
ALTER TABLE batch_card ADD COLUMN imported jsonb;
ALTER TABLE batch_card ADD CONSTRAINT batch_card_from_file CHECK (
    (source = 'file') = (file_name IS NOT NULL) AND (source = 'file') = (imported IS NOT NULL)
);

-- A file's card may have no picture. A photo's card has one until it is approved, as before:
-- the check that said so for every card (0011, (status = 'approved') = (display_key IS NULL))
-- gives way to one that says it for the photos', and the size goes with the picture.
ALTER TABLE batch_card
    ALTER COLUMN width DROP NOT NULL,
    ALTER COLUMN height DROP NOT NULL,
    ALTER COLUMN bytes DROP NOT NULL;
ALTER TABLE batch_card DROP CONSTRAINT batch_card_check2;
ALTER TABLE batch_card ADD CONSTRAINT batch_card_picture CHECK (
    (status <> 'approved' OR display_key IS NULL)
    AND (source = 'file' OR status = 'approved' OR display_key IS NOT NULL)
    AND (width IS NULL) = (height IS NULL)
    AND (width IS NULL) = (bytes IS NULL)
    AND (source = 'file' OR width IS NOT NULL)
    AND (display_key IS NULL OR width IS NOT NULL)
);
