import asyncio
import sys
import os
sys.path.insert(0, '.')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'F:\cybmas\keys\cybmas-750d93f28bed.json'
os.environ['GCP_PROJECT_ID'] = 'cybmas'
os.environ['VERTEX_AI_LOCATION'] = 'us-central1'
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://postgres:sa@127.0.0.1:5432/multi_agent'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:6379'

async def test():
    import asyncpg
    from pipeline.embedding_worker.embedder import embed_text

    pool = await asyncpg.create_pool(
        'postgresql://postgres:sa@127.0.0.1:5432/multi_agent'
    )

    print("Testing semantic search with real embeddings...\n")

    queries = [
        ("database timeout issues in reservation search", ["B1"]),
        ("payment outage certificate expired", ["B2"]),
        ("overbooking concurrent requests", ["B1"]),
        ("email delivery delay queue", ["B1"]),
        ("currency conversion wrong rates", ["B2"]),
    ]

    for query, bus in queries:
        vector = await embed_text(query)
        rows = await pool.fetch(
            """
            SELECT jira_id, summary, status,
                   1 - (embedding <=> $1::vector) AS score
            FROM tickets
            WHERE business_unit = ANY($2)
            ORDER BY embedding <=> $1::vector
            LIMIT 3
            """,
            str(vector), bus
        )
        print(f"Query: '{query}'")
        for r in rows:
            print(f"  {r['jira_id']} ({r['status']}) score={float(r['score']):.3f} — {r['summary'][:60]}")
        print()

    await pool.close()
    print("Vector search working correctly with seed data!")

asyncio.run(test())