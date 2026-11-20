-- Anläggningar (#89 del d2, CAD-06, CAD-15, CAD-21): modules put together, the versions they pin,
-- and the stations in TKL that use an assembly or a single module (Används i).
--
-- An assembly belongs to a person or a club in TrainMeet ID, as a module. Every change is the next
-- revision of the row; its modules (PlacedModule) and joints (Joint) are kept as they were last
-- saved, the placement worked out from the joints. A removed assembly is only no longer seen.

CREATE TABLE assembly (
    id uuid PRIMARY KEY,
    owner_kind text NOT NULL CHECK (owner_kind IN ('person', 'club')),
    owner_id uuid NOT NULL,
    owner_name text NOT NULL CHECK (length(owner_name) BETWEEN 1 AND 80),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    scale text NOT NULL CHECK (scale IN ('H0', 'N', '0')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    modules jsonb NOT NULL DEFAULT '[]'::jsonb,
    joints jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by_name text NOT NULL,
    removed_at timestamptz
);

CREATE INDEX assembly_owner ON assembly (owner_id) WHERE removed_at IS NULL;

-- The module versions an assembly pins (CAD-21), for the module's Används i.
CREATE TABLE assembly_module (
    assembly_id uuid NOT NULL REFERENCES assembly (id) ON DELETE CASCADE,
    module_id uuid NOT NULL REFERENCES module (id),
    version integer NOT NULL CHECK (version >= 1),
    PRIMARY KEY (assembly_id, module_id)
);

CREATE INDEX assembly_module_module ON assembly_module (module_id);

-- A station in TKL that took an assembly or a single module into use, as Studio said when the
-- owner confirmed it (CAD-15). The station's id is TKL's own, so the person is part of the key.
CREATE TABLE station_use (
    source_kind text NOT NULL CHECK (source_kind IN ('assembly', 'module')),
    source_id uuid NOT NULL,
    person uuid NOT NULL,
    station_id text NOT NULL CHECK (length(station_id) BETWEEN 1 AND 80),
    station_name text NOT NULL CHECK (length(station_name) BETWEEN 1 AND 80),
    revision integer NOT NULL CHECK (revision >= 1),
    at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_kind, source_id, person, station_id)
);
