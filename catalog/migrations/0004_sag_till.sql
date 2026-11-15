-- Säg till ägaren (#54): someone logged in who taps another's vehicle can say where it stands.
-- The notice is kept on the vehicle without the sender, and the sender never learns who the
-- owner is (CAT-113).
CREATE TABLE vehicle_notice (
    id uuid PRIMARY KEY,
    vehicle_id uuid NOT NULL REFERENCES vehicle (id) ON DELETE CASCADE,
    text text NOT NULL CHECK (length(text) BETWEEN 1 AND 200),
    at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX vehicle_notice_by_vehicle ON vehicle_notice (vehicle_id, at);
