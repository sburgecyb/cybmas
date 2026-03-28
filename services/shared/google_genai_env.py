"""Map cybmas env vars to google-genai (ADK) Vertex AI settings.

The GenAI SDK defaults to the Gemini Developer API (API key). Vertex AI uses
ADC and expects GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION. The rest of the
repo uses GCP_PROJECT_ID and VERTEX_AI_LOCATION — bridge them before ADK loads.
"""

from __future__ import annotations

import os


def configure_google_genai_for_vertex() -> None:
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        gcp = os.environ.get("GCP_PROJECT_ID")
        if gcp:
            os.environ["GOOGLE_CLOUD_PROJECT"] = gcp
    if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
        loc = os.environ.get("VERTEX_AI_LOCATION")
        if loc:
            os.environ["GOOGLE_CLOUD_LOCATION"] = loc
