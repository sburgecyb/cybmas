-- Seed users for Cloud SQL (run after migrations).
-- Passwords match scripts/seed_users.py defaults.
--
--   admin@company.com      / Admin@1234
--   l1engineer@company.com / Engineer@1234
--   l3engineer@company.com / Engineer@1234
--
-- New bcrypt hash:  python -c "import bcrypt; print(bcrypt.hashpw(b'PASS', bcrypt.gensalt()).decode())"

INSERT INTO users (email, hashed_password, full_name, role)
VALUES
    (
        'admin@company.com',
        '$2b$12$Txh3/a00gEoPw45zym8PZOgqMFrcFVv7MV5ApVlo2NLey0gy6HOMC',
        'System Admin',
        'admin'
    ),
    (
        'l1engineer@company.com',
        '$2b$12$VpyKsrVXHTsCiEJljlr/M.4KTaU462OGsUiI5HVJY.7qvKXCAKtOy',
        'L1/L2 Support Engineer',
        'engineer'
    ),
    (
        'l3engineer@company.com',
        '$2b$12$VpyKsrVXHTsCiEJljlr/M.4KTaU462OGsUiI5HVJY.7qvKXCAKtOy',
        'L3 Support Engineer',
        'engineer'
    )
ON CONFLICT (email) DO NOTHING;