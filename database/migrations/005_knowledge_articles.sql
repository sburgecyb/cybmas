-- Global support knowledge base articles with vector embeddings (768-d, text-embedding-004)
CREATE TABLE knowledge_articles (
    doc_id             TEXT PRIMARY KEY,
    title              TEXT NOT NULL,
    category           TEXT,
    level              TEXT,
    tags               JSONB,
    problem_statement  TEXT,
    symptoms           JSONB,
    possible_causes    JSONB,
    diagnostic_steps   JSONB,
    resolution_steps   JSONB,
    validation         JSONB,
    confidence_score   REAL,
    last_updated       DATE,
    embedding          vector(768),
    raw_json           JSONB
);

CREATE INDEX knowledge_articles_embedding_idx ON knowledge_articles
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX knowledge_articles_category_idx ON knowledge_articles(category);
CREATE INDEX knowledge_articles_level_idx ON knowledge_articles(level);
