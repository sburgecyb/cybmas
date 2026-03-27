# Add to test_webhook.py or create test_jira_client.py
import asyncio
import sys
sys.path.insert(0, '.')
from pipeline.embedding_worker.jira_client import JIRAClient, JIRAClientError

async def test():
    async with JIRAClient() as client:
        # Test ADF extraction
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Hello world"}]
                }
            ]
        }
        text = client.extract_plain_text(adf)
        print(f"ADF extraction: '{text.strip()}'")
        assert "Hello world" in text
        print("OK - JIRA client created and ADF extraction works")

asyncio.run(test())