-- Mätaren (#79, TOKEN-28): svaret från TrainMeets AI hålls ett dygn under reservationen, så att
-- en app som frågar igen med samma reservation får samma svar och inget dras två gånger.
CREATE TABLE meter_answer (
    reservation_id uuid PRIMARY KEY REFERENCES token_reservation (id) ON DELETE CASCADE,
    text text NOT NULL,
    model text NOT NULL CHECK (length(model) BETWEEN 1 AND 120),
    at timestamptz NOT NULL
);

CREATE INDEX meter_answer_at ON meter_answer (at);
