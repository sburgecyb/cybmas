-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Track applied migrations
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(50) PRIMARY KEY,
    applied_at  TIMESTAMPTZ DEFAULT now()
);

-- Engineer accounts (JWT auth)
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(100),
    role            VARCHAR(20) DEFAULT 'engineer' CHECK (role IN ('engineer', 'admin')),
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_login      TIMESTAMPTZ
);
CREATE INDEX users_email_idx ON users(email);

-- Business units
CREATE TABLE business_units (
    id    SERIAL PRIMARY KEY,
    code  VARCHAR(20) UNIQUE NOT NULL,
    name  VARCHAR(100)
);

-- JIRA tickets with vector embeddings
CREATE TABLE tickets (
    id            SERIAL PRIMARY KEY,
    jira_id       VARCHAR(50) UNIQUE NOT NULL,
    business_unit VARCHAR(20) REFERENCES business_units(code),
    ticket_type   VARCHAR(20),
    summary       TEXT NOT NULL,
    description   TEXT,
    status        VARCHAR(50),
    resolution    TEXT,
    discussion    JSONB,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    embedding     vector(768),
    raw_json      JSONB
);

-- Incident reports and RCAs
CREATE TABLE incidents (
    id              SERIAL PRIMARY KEY,
    jira_id         VARCHAR(50) UNIQUE,
    business_unit   VARCHAR(20),
    title           TEXT NOT NULL,
    description     TEXT,
    root_cause      TEXT,
    long_term_fix   TEXT,
    related_tickets JSONB,
    severity        VARCHAR(20),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    embedding       vector(768),
    raw_json        JSONB
);

-- Chat sessions
CREATE TABLE chat_sessions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engineer_id   VARCHAR(100) NOT NULL,
    title         TEXT,
    context_scope JSONB,
    messages      JSONB,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX chat_sessions_engineer_idx ON chat_sessions(engineer_id, updated_at DESC);

-- Engineer feedback
CREATE TABLE engineer_feedback (
    id            SERIAL PRIMARY KEY,
    session_id    UUID REFERENCES chat_sessions(id),
    message_index INT,
    rating        VARCHAR(20) CHECK (rating IN ('correct', 'can_be_better', 'incorrect')),
    comment       TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX feedback_session_idx ON engineer_feedback(session_id);
