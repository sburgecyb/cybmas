import asyncio
import sys
import os
sys.path.insert(0, '.')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'F:\cybmas\keys\cybmas-750d93f28bed.json'
os.environ['GCP_PROJECT_ID'] = 'your-gcp-project-id'

import google.generativeai as genai
genai.configure()
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)
        
async def test():
    from services.shared.skills.summarize import summarize_search_results

    # Test 1 - Empty results
    result = await summarize_search_results(
        original_question="database timeout issues",
        search_results=[],
        result_type="tickets"
    )
    assert result['success'] == True
    assert 'No relevant results' in result['data']['summary']
    print("OK - Empty results handled correctly")

    # Test 2 - With sample results (calls real Gemini)
    sample_results = [
        {
            "jira_id": "B1-1008",
            "title": "Search API response time degrading under high load",
            "summary": "p95 latency exceeding 3 seconds since v2.5.0 deployment",
            "score": 0.91,
            "result_type": "ticket",
            "status": "Open",
            "business_unit": "B1",
            "metadata": {}
        },
        {
            "jira_id": "B1-1013",
            "title": "Add database connection pooling",
            "summary": "Each instance opening direct connections exhausting max_connections",
            "score": 0.85,
            "result_type": "ticket",
            "status": "Resolved",
            "business_unit": "B1",
            "metadata": {}
        }
    ]

    result = await summarize_search_results(
        original_question="We are seeing database performance issues",
        search_results=sample_results,
        result_type="tickets"
    )

    assert result['success'] == True
    assert len(result['data']['summary']) > 50
    print(f"OK - Gemini summarised results successfully")
    print(f"     Summary preview: {result['data']['summary'][:100]}...")
    print(f"     Key points: {len(result['data']['key_points'])}")
    print(f"     Follow-ups: {len(result['data']['suggested_follow_ups'])}")

    print("\nAll summarize tests passed")

asyncio.run(test())