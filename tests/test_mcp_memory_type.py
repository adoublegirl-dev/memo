from memo.core.engine import normalize_memory_type
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
