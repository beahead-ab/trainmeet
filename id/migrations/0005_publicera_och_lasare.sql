-- Planeringens roller (PLAN-19, PLAN-24, H16, #78): Arrangör med publicering som tillval per
-- träff, och Läsare. Läsare fanns redan med i listan; Får publicera är ny.
ALTER TABLE role_grant DROP CONSTRAINT role_grant_role_check;
ALTER TABLE role_grant ADD CONSTRAINT role_grant_role_check CHECK (role IN ('admin', 'member',
    'organizer', 'publisher', 'reader', 'dispatcher', 'loco_lead', 'remote_clearer', 'reviewer',
    'viewer', 'editor'));
