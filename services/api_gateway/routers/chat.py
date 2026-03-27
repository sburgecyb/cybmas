"""Chat router — handles streaming and non-streaming chat requests."""
from fastapi import APIRouter

router = APIRouter(tags=["chat"])

# TODO: implement POST /chat/stream (SSE) and POST /chat/message
