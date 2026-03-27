# Google ADK Setup Guide

This guide covers setting up Google ADK for local development using Vertex AI (Gemini + text-embedding-004) authenticated via a service account JSON key.

---

## Prerequisites

- Python 3.11+
- GCP project with Vertex AI API enabled
- Service account JSON key file (`cybmasacn.json`) in your `keys/` folder
- Service account has roles: **Vertex AI User** + **Vertex AI Service Agent**

---

## Step 1 — Create Python Virtual Environment

```cmd
python -m venv venv

# Activate (Command Prompt)
venv\Scripts\activate

# Activate (PowerShell)
venv\Scripts\Activate.ps1
```

Keep this active for all development work.

---

## Step 2 — Install Google ADK and Dependencies

```cmd
pip install google-adk
pip install google-cloud-aiplatform
pip install vertexai
pip install fastapi uvicorn asyncpg redis httpx structlog pydantic
```

Verify ADK installed:
```cmd
adk --version
```

---

## Step 3 — Set Environment Variables

In your `.env.local`:
```
GOOGLE_APPLICATION_CREDENTIALS=C:\keys\cybmasacn.json
GCP_PROJECT_ID=your-gcp-project-id
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-1.5-flash
EMBEDDING_MODEL=text-embedding-004
EMBEDDING_DIMENSIONS=768
```

ADK, Vertex AI SDK, and google-generativeai all automatically read `GOOGLE_APPLICATION_CREDENTIALS` — no auth code needed in your application.

---

## Step 4 — Verify Credentials Work

Create `test_credentials.py`:

```python
import os
import vertexai
from vertexai.language_models import TextEmbeddingModel
import google.generativeai as genai

# Test 1: Vertex AI embeddings
vertexai.init(
    project=os.getenv("GCP_PROJECT_ID"),
    location=os.getenv("VERTEX_AI_LOCATION", "us-central1")
)
model = TextEmbeddingModel.from_pretrained("text-embedding-004")
result = model.get_embeddings(["test query"])
print(f"✅ Embeddings working — dims: {len(result[0].values)}")  # should print 768

# Test 2: Gemini LLM
genai.configure()  # picks up GOOGLE_APPLICATION_CREDENTIALS automatically
gemini = genai.GenerativeModel("gemini-1.5-flash")
response = gemini.generate_content("Say hello in one word")
print(f"✅ Gemini working — response: {response.text}")
```

Run it:
```cmd
python test_credentials.py
```

Both checks should pass before running any Cursor prompts.

---

## Step 5 — Verify ADK + Gemini Works

Create `test_adk.py`:

```python
import asyncio
import os
from google.adk.agents import LlmAgent
from google.adk.tools import tool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.types import Content, Part

@tool
def get_greeting(name: str) -> str:
    """Returns a greeting for the given name."""
    return f"Hello {name}, welcome to the support system!"

async def main():
    agent = LlmAgent(
        name="test_agent",
        model="gemini-1.5-flash",  # uses GOOGLE_APPLICATION_CREDENTIALS automatically
        instruction="You are a helpful assistant. Use tools when appropriate.",
        tools=[get_greeting],
    )

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="test", session_service=session_service)
    session = await session_service.create_session(app_name="test", user_id="test_user")

    result = runner.run(
        user_id="test_user",
        session_id=session.id,
        new_message=Content(parts=[Part(text="Say hello to Alice")])
    )

    async for event in result:
        if event.content:
            for part in event.content.parts:
                if part.text:
                    print(f"✅ ADK + Gemini working — response: {part.text}")

asyncio.run(main())
```

Run it:
```cmd
python test_adk.py
```

---

## Step 6 — Use ADK Web UI (Optional)

ADK has a built-in browser UI for testing agents interactively:

```cmd
cd services/l1l2-agent
adk web
```

Open `http://localhost:8000` to chat with the agent directly — useful for testing tool calls without running the full stack.

---

## ADK Key Patterns Used in This Project

### LlmAgent Definition
```python
from google.adk.agents import LlmAgent
from google.adk.tools import tool

@tool
def search_tickets(query_text: str, business_units: list[str]) -> dict:
    """Search historical support tickets by semantic similarity.
    
    Args:
        query_text: Description of the problem to search for
        business_units: List of BU codes to search within e.g. ['B1', 'B2']
    
    Returns:
        Dictionary with list of matching tickets and relevance scores
    """
    # implementation here
    ...

agent = LlmAgent(
    name="l1l2_resolution_agent",
    model="gemini-1.5-flash",
    instruction="Your system prompt here...",
    tools=[search_tickets],
)
```

### Multi-Agent Delegation (Orchestrator)
```python
from google.adk.agents import LlmAgent

l1l2_agent = LlmAgent(name="l1l2_agent", model="gemini-1.5-flash", ...)
l3_agent   = LlmAgent(name="l3_agent",   model="gemini-1.5-flash", ...)

orchestrator = LlmAgent(
    name="orchestrator",
    model="gemini-1.5-flash",
    instruction="Route queries to the right specialist agent...",
    agents=[l1l2_agent, l3_agent],  # sub-agents registered here
)
```

### Embeddings in Tools
```python
import vertexai
from vertexai.language_models import TextEmbeddingModel

vertexai.init(project=os.getenv("GCP_PROJECT_ID"), location="us-central1")
_embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")

async def embed_text(text: str) -> list[float]:
    result = _embedding_model.get_embeddings([text])
    return result[0].values  # 768-dim vector
```

---

## Production Difference

In production (Cloud Run), remove `GOOGLE_APPLICATION_CREDENTIALS` from env vars entirely. Cloud Run uses the **service account attached to the Cloud Run service** via Workload Identity — zero key file management.

The application code is **identical** in both environments.

---

## Troubleshooting

**`DefaultCredentialsError`**: Check `GOOGLE_APPLICATION_CREDENTIALS` path is correct and the file exists.

**`Permission denied` on Vertex AI**: Ensure service account has `Vertex AI User` role in GCP IAM.

**`adk` command not found**: Activate your virtual environment first: `venv\Scripts\activate`

**`ModuleNotFoundError: google.adk`**: Run `pip install google-adk` inside activated venv.
