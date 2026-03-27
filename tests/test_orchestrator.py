import asyncio
import sys
import os
sys.path.insert(0, '.')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'F:\cybmas\keys\cybmas-750d93f28bed.json'
os.environ['GCP_PROJECT_ID'] = 'cybmas'
os.environ['GEMINI_MODEL'] = 'gemini-2.5-flash'
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://postgres:sa@127.0.0.1:5432/multi_agent'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:6379'
os.environ['L1L2_AGENT_ENDPOINT'] = 'http://localhost:8002'
os.environ['L3_AGENT_ENDPOINT'] = 'http://localhost:8003'
os.environ['SESSION_AGENT_ENDPOINT'] = 'http://localhost:8004'

async def test():
    from services.orchestrator.intent_classifier import classify_intent, IntentType
    from services.orchestrator.router import route_to_agent
    from services.shared.models import BusinessUnitScope

    scope_no_incidents = BusinessUnitScope(
        business_units=["B1"],
        include_incidents=False
    )
    scope_with_incidents = BusinessUnitScope(
        business_units=["B1", "B2"],
        include_incidents=True
    )

    # Test 1 - JIRA ID pattern detection
    intent = await classify_intent("What happened with B1-1008?", scope_no_incidents)
    assert intent == IntentType.JIRA_LOOKUP, f"Expected JIRA_LOOKUP got {intent}"
    print(f"OK - JIRA ID detected: {intent}")

    # Test 2 - Status check
    intent = await classify_intent("What is the status of B2-2004?", scope_no_incidents)
    assert intent in [IntentType.STATUS_CHECK, IntentType.JIRA_LOOKUP]
    print(f"OK - Status check detected: {intent}")

    # Test 3 - Incident search (with incidents enabled)
    intent = await classify_intent(
        "Have we had any database outages before?",
        scope_with_incidents
    )
    assert intent == IntentType.INCIDENT_SEARCH, f"Expected INCIDENT_SEARCH got {intent}"
    print(f"OK - Incident search detected: {intent}")

    # Test 4 - Regular ticket search
    intent = await classify_intent(
        "We are seeing timeout errors in the reservation service",
        scope_no_incidents
    )
    assert intent == IntentType.TICKET_SEARCH, f"Expected TICKET_SEARCH got {intent}"
    print(f"OK - Ticket search detected: {intent}")

    # Test 5 - Routing
    endpoint = route_to_agent(IntentType.TICKET_SEARCH, scope_no_incidents)
    assert endpoint == 'http://localhost:8002'
    print(f"OK - TICKET_SEARCH routes to L1L2: {endpoint}")

    endpoint = route_to_agent(IntentType.INCIDENT_SEARCH, scope_with_incidents)
    assert endpoint == 'http://localhost:8003'
    print(f"OK - INCIDENT_SEARCH routes to L3: {endpoint}")

    # Test 6 - Orchestrator agent
    from services.orchestrator.agent import agent
    print(f"\nOK - Orchestrator agent: {agent.name}")
    print(f"     Sub-agents: {[a.name for a in agent.sub_agents]}")

    print("\nAll orchestrator tests passed")

asyncio.run(test())