-- Landskapet (#89 del d1, CAD-04, CAD-08, CAD-33): a module version's surfaces.
--
-- The landscape belongs to the module version it was saved in (CAD-08), and a later version
-- keeps it until a new one is saved: the landscape of version v is the row with the highest
-- version up to v. Every save is a new module version, so a row is never changed.
--
-- The cells are a grid over the module in its own millimetres (cad/landskap.py): cell (0, 0)'s
-- corner at (x0, y0), cell mm on a side, one byte per cell (the surface's code, with 0x80 where
-- the owner painted it), kept as a PNG. made_by names the model or the clustering that made it;
-- photo_job the measuring image it was made from.

CREATE TABLE module_landscape (
    module_id uuid NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    method text NOT NULL CHECK (method IN ('model', 'colour', 'hand')),
    made_by text NOT NULL CHECK (length(made_by) BETWEEN 1 AND 80),
    photo_job uuid,
    x0 double precision NOT NULL,
    y0 double precision NOT NULL,
    cell double precision NOT NULL CHECK (cell > 0 AND cell <= 50),
    width integer NOT NULL CHECK (width BETWEEN 1 AND 4000),
    height integer NOT NULL CHECK (height BETWEEN 1 AND 4000),
    cells bytea NOT NULL CHECK (length(cells) <= 8388608),
    saved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (module_id, version),
    FOREIGN KEY (module_id, version) REFERENCES module_version (module_id, version)
        ON DELETE CASCADE
);
