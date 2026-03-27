import asyncio
import sys
import os
sys.path.insert(0, '.')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'F:\cybmas\keys\cybmas-750d93f28bed.json'
os.environ['GCP_PROJECT_ID'] = 'cybmas'
os.environ['VERTEX_AI_LOCATION'] = 'us-central1'

async def test():
    from pipeline.embedding_worker.embedder import embed_text, embed_batch

    # Test single embedding
    vector = await embed_text("Database connection timeout in reservation service")
    print(f"OK - embed_text: {len(vector)} dimensions")
    assert len(vector) == 768, f"Expected 768 dims, got {len(vector)}"

    # Test processor
    from pipeline.embedding_worker.processor import prepare_ticket_text
    ticket = {
        "summary": "Test ticket",
        "ticket_type": "BUG",
        "status": "Open",
        "description": "Test description",
        "resolution": None,
        "discussion": []
    }
    text = prepare_ticket_text(ticket)
    print(f"OK - prepare_ticket_text: {len(text)} chars")

    print("All embedder tests passed")

asyncio.run(test())