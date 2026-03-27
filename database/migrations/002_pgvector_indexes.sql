-- HNSW indexes for fast cosine similarity search
CREATE INDEX tickets_embedding_idx ON tickets
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX incidents_embedding_idx ON incidents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- B-tree indexes for filtering
CREATE INDEX tickets_bu_idx ON tickets(business_unit);
CREATE INDEX tickets_status_idx ON tickets(status);
CREATE INDEX tickets_type_idx ON tickets(ticket_type);
CREATE INDEX incidents_bu_idx ON incidents(business_unit);
CREATE INDEX incidents_severity_idx ON incidents(severity);
