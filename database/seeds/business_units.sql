INSERT INTO business_units (code, name) VALUES
    ('B1', 'Reservations Platform'),
    ('B2', 'Payments Platform')
ON CONFLICT (code) DO NOTHING;
