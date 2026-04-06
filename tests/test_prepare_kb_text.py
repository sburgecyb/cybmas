"""Unit tests for KB embedding text preparation."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.embedding_worker.processor import prepare_kb_text


def test_prepare_kb_text_includes_core_fields():
    doc = {
        "doc_id": "KB-1000",
        "title": "Infrastructure Disk Space Full",
        "category": "Infrastructure",
        "level": "L1",
        "tags": ["infrastructure", "disk"],
        "problem_statement": "Disk full impacting performance.",
        "symptoms": ["Slow responses"],
        "possible_causes": [{"cause": "Resource exhaustion", "confidence": 0.5}],
        "diagnostic_steps": ["Check logs"],
        "resolution_steps": ["Free space"],
        "validation": ["System OK"],
    }
    text = prepare_kb_text(doc)
    assert "Infrastructure Disk Space Full" in text
    assert "Infrastructure" in text
    assert "disk" in text.lower()
    assert "Disk full" in text
    assert "Resource exhaustion" in text
    assert "Check logs" in text
    assert "Free space" in text
    assert "System OK" in text


def test_prepare_kb_text_truncates_safely():
    doc = {
        "doc_id": "KB-1",
        "title": "T",
        "problem_statement": "x" * 5000,
    }
    text = prepare_kb_text(doc)
    assert len(text) <= 3000


if __name__ == "__main__":
    test_prepare_kb_text_includes_core_fields()
    test_prepare_kb_text_truncates_safely()
    print("OK: prepare_kb_text tests passed")
