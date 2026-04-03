-- Fallback BU for JIRA issues not mapped via BU_B1_PROJECTS / BU_B2_PROJECTS
INSERT INTO business_units (code, name) VALUES
    ('Default', 'Unmapped / default')
ON CONFLICT (code) DO NOTHING;
