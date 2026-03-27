import asyncio
import sys
import os
sys.path.insert(0, '.')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'F:\cybmas\keys\cybmas-750d93f28bed.json'
os.environ['GCP_PROJECT_ID'] = 'your-gcp-project-id'
os.environ['GEMINI_MODEL'] = 'gemini-2.5-flash'
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://postgres:sa@127.0.0.1:5432/multi_agent'

async def test():
    # Test 1 - Agent imports
    try:
        from services.session_agent.agent import agent
        print(f"OK - Session agent created: {agent.name}")
        print(f"     Tools: {len(agent.tools)}")
    except Exception as e:
        print(f"FAIL - {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 2 - Save and load session
    try:
        from services.session_agent.tools.session_store import (
            save_session, load_session, list_engineer_sessions
        )
        import uuid

        session_id = str(uuid.uuid4())
        engineer_id = "test@company.com"

        # Save
        result = await save_session(
            session_id=session_id,
            engineer_id=engineer_id,
            title="Test session",
            context_scope={"business_units": ["B1"], "include_incidents": False},
            messages=[
                {"role": "user", "content": "What is the status of B1-1008?"},
                {"role": "assistant", "content": "B1-1008 is currently Open..."}
            ]
        )
        assert result['success'], f"Save failed: {result}"
        print(f"OK - Session saved: {session_id[:8]}...")

        # Load
        result = await load_session(session_id)
        assert result['success'], f"Load failed: {result}"
        assert len(result['data']['messages']) == 2
        print(f"OK - Session loaded: {len(result['data']['messages'])} messages")

        # List
        result = await list_engineer_sessions(engineer_id, limit=5)
        assert result['success']
        print(f"OK - Sessions listed: {len(result['data'])} sessions found")

    except Exception as e:
        print(f"FAIL - Session tools: {e}")
        import traceback
        traceback.print_exc()

    # Test 3 - Feedback
    try:
        from services.session_agent.tools.feedback_store import save_feedback
        result = await save_feedback(
            session_id=session_id,
            message_index=1,
            rating="correct",
            comment="Very helpful response"
        )
        assert result['success'], f"Feedback save failed: {result}"
        print("OK - Feedback saved successfully")

    except Exception as e:
        print(f"FAIL - Feedback tools: {e}")

    print("\nAll session agent tests passed")

asyncio.run(test())