-- Ta bort kontot (KONTO-31, ID7): en klubb som personen skapade ligger kvar hos klubben när
-- någon annan är administratör, så den som skapade den får saknas.
ALTER TABLE club ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE club DROP CONSTRAINT club_created_by_fkey;
ALTER TABLE club ADD CONSTRAINT club_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES person (id) ON DELETE SET NULL;
