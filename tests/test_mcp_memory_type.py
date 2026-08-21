from pathlib import Path

from memo.core.engine import normalize_memory_type
from memo.extraction.extractor import _normalize_extraction
from memo.models import MemoryType


def test_mcp_memory_type_string_is_normalized_to_enum():
    assert normalize_memory_type("FACT") is MemoryType.FACT
    assert normalize_memory_type("decision") is MemoryType.DECISION


def test_mcp_memory_type_enum_is_preserved():
    assert normalize_memory_type(MemoryType.PREFERENCE) is MemoryType.PREFERENCE


def test_mcp_memory_type_rejects_unknown_value():
    try:
        normalize_memory_type("unknown")
    except ValueError as exc:
        assert "expected one of" in str(exc)
    else:
        raise AssertionError("unknown memory type should be rejected")


def test_llm_extraction_normalizes_lowercase_memory_type():
    result = _normalize_extraction({"memory_type": "decision"})
    assert result["memory_type"] == "DECISION"


def test_llm_extraction_falls_back_to_fact_for_unknown_memory_type():
    result = _normalize_extraction({"memory_type": "unexpected-value"})
    assert result["memory_type"] == "FACT"


def test_automatic_conversation_path_uses_shared_memory_type_normalizer():
    engine_source = Path(__file__).parents[1].joinpath("memo", "core", "engine.py").read_text(encoding="utf-8")
    assert 'memory_type=normalize_memory_type(extracted.get("memory_type", "FACT"))' in engine_source
