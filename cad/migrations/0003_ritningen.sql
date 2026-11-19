-- Ritningen (#89 del b): what a version keeps of its drawing besides the graph (DrawingState in
-- contracts/cad.py): where the track plan comes from, the utjämning, the owner's answers in Att
-- kolla, the drawn lines, the locked measures, and the ids this version split (CAD-20). A version
-- is still never changed; the drawing is saved with it.

ALTER TABLE module_version ADD COLUMN drawing jsonb NOT NULL DEFAULT '{}'::jsonb;
