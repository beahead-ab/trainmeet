-- Betald lagring över den fria nivån (CAT-132, TOKEN-16, TOKEN-29): det som är betalt per ägare
-- och månad.
--
-- Over the free level, 100 MB for a person and 2 GB for a club's fleet, every started GB costs
-- 20 tokens a month from the owner's balance in TrainMeet ID (TK10). blocks is how many started
-- GB are paid for the month, in Swedish time; it never goes down within the month. Each GB is
-- drawn in ID with a key of its own, so the same GB is never paid twice (catalog/storage.py).
-- unpaid says that the month's charge could not be drawn, the balance being short or the day's
-- cap reached: the pictures stay, but nothing that grows the storage is saved until it is paid
-- (TK15). club says whose balance paid, the club's or the person's, as ID said at the charge
-- (TOKEN-29), for the daily round, which has no person to ask ID with.

CREATE TABLE storage_charge (
    owner_id uuid NOT NULL REFERENCES owner (id) ON DELETE CASCADE,
    month text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    blocks integer NOT NULL DEFAULT 0 CHECK (blocks >= 0),
    club boolean NOT NULL,
    unpaid boolean NOT NULL DEFAULT false,
    changed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, month)
);
