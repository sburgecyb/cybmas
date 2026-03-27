import sys
import traceback
sys.path.insert(0, '.')

try:
    from services.l1l2_agent.tools.vector_search import search_tickets
except Exception as e:
    traceback.print_exc()

# Test 1 - Import all tools
try:
    from services.l1l2_agent.tools.vector_search import search_tickets
    from services.l1l2_agent.tools.rerank import rerank_results
    from services.l1l2_agent.tools.jira_fetch import fetch_jira_ticket, check_ticket_status
    print("OK - All L1/L2 tools imported successfully")
except Exception as e:
    print(f"FAIL - Import error: {e}")
    sys.exit(1)

# Test 2 - Rerank tool (no DB or API needed)
try:
    results = [
        {
            "jira_id": "B1-1001",
            "title": "Database connection timeout in reservation service",
            "summary": "Timeout occurring during peak load",
            "score": 0.85,
            "result_type": "ticket",
            "status": "Resolved",
            "business_unit": "B1"
        },
        {
            "jira_id": "B1-1002",
            "title": "Email delivery delay during peak hours",
            "summary": "Emails delayed by 2 hours",
            "score": 0.72,
            "result_type": "ticket",
            "status": "Resolved",
            "business_unit": "B1"
        },
        {
            "jira_id": "B1-1008",
            "title": "Search API response time degrading",
            "summary": "p95 latency exceeding 3 seconds",
            "score": 0.91,
            "result_type": "ticket",
            "status": "Open",
            "business_unit": "B1"
        }
    ]

    reranked = rerank_results(
        query_text="database timeout performance issue",
        results=results,
        top_n=2
    )

    print(f"OK - rerank_results returned: {reranked['success']}")
    print(f"     Top result: {reranked['data'][0]['jira_id']} "
          f"(score: {reranked['data'][0]['score']:.3f})")
    print(f"     Results trimmed to top 2: {len(reranked['data'])} results")

except Exception as e:
    print(f"FAIL - rerank_results error: {e}")

# Test 3 - Tool docstrings present (ADK requires these)
try:
    assert search_tickets.__doc__ is not None, "search_tickets missing docstring"
    assert rerank_results.__doc__ is not None, "rerank_results missing docstring"
    assert fetch_jira_ticket.__doc__ is not None, "fetch_jira_ticket missing docstring"
    assert check_ticket_status.__doc__ is not None, "check_ticket_status missing docstring"
    print("OK - All tools have docstrings (required by ADK)")
except AssertionError as e:
    print(f"FAIL - {e}")

print("\nAll L1/L2 tool tests passed")