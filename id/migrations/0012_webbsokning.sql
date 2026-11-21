-- Webbsökningen genom mätaren (#53 del b, TOKEN-30, CAT-172, C40).
--
-- The meter keeps a search's answer under its reservation as it keeps a reading's, so the same
-- reservation twice gives the same answer and draws nothing twice (TOKEN-28). kind tells the two
-- apart: a reservation that was read with is never searched with, and the other way round.
ALTER TABLE meter_answer
    ADD COLUMN kind text NOT NULL DEFAULT 'read' CHECK (kind IN ('read', 'search'));

-- A reservation that paid for a web search can be refunded once, when the prototype the search
-- led to is approved (CAT-172): search marks it, refunded is what came back, and refunded_at
-- when. The reservation is then returned, with nothing drawn.
ALTER TABLE token_reservation
    ADD COLUMN search boolean NOT NULL DEFAULT false,
    ADD COLUMN refunded integer NOT NULL DEFAULT 0 CHECK (refunded >= 0),
    ADD COLUMN refunded_at timestamptz,
    ADD CHECK (refunded = 0 OR refunded_at IS NOT NULL);

-- What the searches cost, beside the readings (TOKEN-05, TK15): a row is a reading's pages or a
-- search's searches. The month's budget counts both; the measured cost per page counts only the
-- pages, and the measured cost per search only the searches.
ALTER TABLE meter_usage
    ADD COLUMN searches integer NOT NULL DEFAULT 0 CHECK (searches >= 0),
    DROP CONSTRAINT meter_usage_pages_check,
    ADD CONSTRAINT meter_usage_pages_check CHECK (pages >= 0),
    ADD CONSTRAINT meter_usage_something CHECK (pages + searches > 0);
