import sys
import os
sys.path.insert(0, '.')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'F:\cybmas\keys\cybmasacn.json'
os.environ['GCP_PROJECT_ID'] = 'your-gcp-project-id'
os.environ['GEMINI_MODEL'] = 'gemini-2.5-flash'

# Test 1 - Agent imports correctly
try:
    from services.l1l2_agent.agent import agent
    print(f"OK - L1/L2 agent created: {agent.name}")
    print(f"     Model: {agent.model}")
    print(f"     Tools: {len(agent.tools)}")
    print(f"     Instruction length: {len(agent.instruction)} chars")
except Exception as e:
    print(f"FAIL - Agent creation error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2 - Verify all tools registered
try:
    tool_names = [t.__name__ if hasattr(t, '__name__') else str(t) 
                  for t in agent.tools]
    print(f"\nOK - Registered tools: {tool_names}")
    assert len(agent.tools) == 5, f"Expected 5 tools, got {len(agent.tools)}"
except Exception as e:
    print(f"FAIL - Tool check: {e}")

# Test 3 - Agent has description (needed for orchestrator delegation)
try:
    assert agent.description, "Agent missing description"
    print(f"OK - Agent description present: {agent.description[:60]}...")
except AssertionError as e:
    print(f"FAIL - {e}")

print("\nL1/L2 agent tests passed")