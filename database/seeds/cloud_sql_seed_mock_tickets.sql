-- Minimal mock tickets + incidents for Cloud SQL (run after migrations + users optional).
--
-- Uses a fixed 768-d placeholder embedding [1,0,0,...] so vector search runs.
-- All rows share the same embedding (semantic ranking is not meaningful).
-- For realistic embeddings, run:  python scripts/seed_demo_data.py

INSERT INTO business_units (code, name) VALUES
    ('B1', 'Reservations Platform'),
    ('B2', 'Payments Platform'),
    ('Default', 'Unmapped / default')
ON CONFLICT (code) DO NOTHING;

INSERT INTO tickets (
    jira_id, business_unit, ticket_type, summary, description, status, resolution,
    discussion, created_at, updated_at, embedding, raw_json
) VALUES
    (
        'B1-1001',
        'B1',
        'BUG',
        'Search results returning stale availability data after cache flush',
        'After cache flush, availability API served stale data for up to 45 minutes.',
        'Resolved',
        'Fixed Redis cache warm-up readiness gate before marking cache ready.',
        '[]'::jsonb,
        timestamptz '2024-05-01 10:00:00+00',
        timestamptz '2024-05-02 15:00:00+00',
        ('[1' || repeat(',0', 767) || ']')::vector,
        NULL
    ),
    (
        'B1-1008',
        'B1',
        'BUG',
        'Database connection pool exhausting Cloud SQL max connections',
        'Reservation service opened too many direct DB connections during peak load.',
        'Resolved',
        'Deployed PgBouncer; pool size 25 per instance; connections stable.',
        '[]'::jsonb,
        timestamptz '2024-05-10 09:00:00+00',
        timestamptz '2024-05-11 12:00:00+00',
        ('[1' || repeat(',0', 767) || ']')::vector,
        NULL
    ),
    (
        'B2-2004',
        'B2',
        'INCIDENT',
        'Payment processing outage — card payments failing for 23 minutes',
        'TLS certificate for Stripe API connection had expired; renewal job failed silently.',
        'Resolved',
        'Certificate renewed; expiry monitoring with 30-day alerts.',
        '[{"author":"ops","body":"Restored 14:45 UTC"}]'::jsonb,
        timestamptz '2024-03-15 14:20:00+00',
        timestamptz '2024-03-15 15:00:00+00',
        ('[1' || repeat(',0', 767) || ']')::vector,
        NULL
    )
ON CONFLICT (jira_id) DO NOTHING;

INSERT INTO incidents (
    jira_id, business_unit, title, description, root_cause, long_term_fix,
    related_tickets, severity, resolved_at, created_at, updated_at, embedding, raw_json
) VALUES
    (
        'INC-001',
        'B1',
        'Reservation search partial outage',
        'Elevated 5xx errors on search API for 12 minutes during deploy.',
        'Rolling deploy left one pod on old config without updated DB pool settings.',
        'Added pre-deploy config validation; canary checks pool connectivity.',
        '["B1-1001"]'::jsonb,
        'high',
        timestamptz '2024-06-01 18:00:00+00',
        timestamptz '2024-06-01 17:45:00+00',
        timestamptz '2024-06-01 18:30:00+00',
        ('[1' || repeat(',0', 767) || ']')::vector,
        NULL
    )
ON CONFLICT (jira_id) DO NOTHING;
