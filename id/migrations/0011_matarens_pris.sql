-- Mätaren håller reservationen (#52, CAT-145): med hold läser mätaren och behåller svaret utan
-- att dra, och appen drar sedan det svaret kostade. Priset behålls med svaret, så att samma
-- reservation igen ger samma pris: 12 tokens per bild, eller 0 med egen AI (TK4), också när
-- kontots egna AI har kopplats in eller ur under tiden. Äldre svar är redan dragna och har inget
-- pris här; deras pris är det dragna.
ALTER TABLE meter_answer ADD COLUMN cost integer CHECK (cost >= 0);
