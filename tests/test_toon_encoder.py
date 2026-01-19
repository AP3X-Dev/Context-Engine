"""Tests for TOON (Token-Oriented Object Notation) encoder.

Tests verify round-trip encoding/decoding using the official python-toon library.
"""

import os
import pytest
from toon import decode as toon_decode

# Ensure scripts module is importable
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.toon_encoder import (
    encode,
    encode_search_results,
    encode_context_results,
    compare_formats,
    is_toon_enabled,
)


class TestFeatureFlags:
    """Test feature flag behavior."""

    def test_toon_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("TOON_ENABLED", raising=False)
        assert is_toon_enabled() is False

    def test_toon_enabled_when_set(self, monkeypatch):
        monkeypatch.setenv("TOON_ENABLED", "1")
        assert is_toon_enabled() is True

        monkeypatch.setenv("TOON_ENABLED", "true")
        assert is_toon_enabled() is True


class TestCoreEncoding:
    """Test core encoding with round-trip verification."""

    def test_encode_primitives(self):
        """Encode primitives and verify round-trip."""
        data = {"null_val": None, "bool_true": True, "bool_false": False, "int_val": 42, "float_val": 3.14, "str_val": "hello"}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_string_with_special_chars(self):
        """Strings with special characters should round-trip correctly."""
        data = {"comma": "hello,world", "newline": "line1\nline2", "quote": 'say "hi"'}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_nested_object(self):
        """Nested objects should round-trip correctly."""
        data = {"outer": {"inner": {"value": 123}}}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_array_of_objects(self):
        """Arrays of objects should round-trip correctly."""
        data = {"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_simple_array(self):
        """Simple arrays should round-trip correctly."""
        data = {"numbers": [1, 2, 3], "strings": ["a", "b", "c"]}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_empty_structures(self):
        """Empty structures should round-trip correctly."""
        data = {"empty_list": [], "empty_dict": {}}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_mixed_structure(self):
        """Mixed nested structures should round-trip correctly."""
        data = {
            "users": [{"id": 1, "tags": ["admin", "user"]}, {"id": 2, "tags": []}],
            "meta": {"count": 2, "nested": {"deep": True}}
        }
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data


class TestTabularEncoding:
    """Test tabular array encoding via round-trip."""

    def test_encode_tabular_basic(self):
        """Tabular data should round-trip correctly."""
        data = {"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data
        assert len(decoded["users"]) == 2
        assert decoded["users"][0]["name"] == "Alice"

    def test_encode_tabular_single_item(self):
        """Single item arrays should round-trip correctly."""
        data = {"items": [{"x": 1}]}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_tabular_tab_delimiter(self):
        """Tab delimiter should work correctly."""
        data = {"data": [{"a": 1, "b": 2}]}
        encoded = encode(data, delimiter="\t")
        decoded = toon_decode(encoded)
        assert decoded == data

    def test_encode_empty_array(self):
        """Empty arrays should round-trip correctly."""
        data = {"empty": []}
        encoded = encode(data)
        decoded = toon_decode(encoded)
        assert decoded == data


class TestSearchResults:
    """Test search result encoding specifically."""

    def test_encode_search_results_compact(self):
        """Compact mode should only include core fields and round-trip correctly."""
        results = [
            {"path": "/src/main.py", "start_line": 10, "end_line": 20, "score": 0.95},
            {"path": "/src/utils.py", "start_line": 5, "end_line": 15, "score": 0.87},
        ]
        output = encode_search_results(results, compact=True)
        decoded = toon_decode(output)
        # Verify core fields present
        assert decoded["results"][0]["path"] == "/src/main.py"
        assert decoded["results"][0]["start_line"] == 10
        assert decoded["results"][0]["end_line"] == 20
        # Score should be excluded in compact mode
        assert "score" not in decoded["results"][0]

    def test_encode_search_results_full(self):
        """Full mode should include all fields and round-trip correctly."""
        results = [
            {"path": "/src/main.py", "start_line": 10, "end_line": 20, "score": 0.95, "symbol": "main"},
        ]
        output = encode_search_results(results, compact=False)
        assert "score" in output
        assert "0.95" in output
        # Verify round-trip decoding works
        from toon import decode
        decoded = decode(output)
        assert decoded["results"][0]["score"] == 0.95

    def test_encode_empty_results(self):
        output = encode_search_results([])
        # Verify it decodes to empty results
        from toon import decode
        decoded = decode(output)
        assert decoded["results"] == []


class TestTokenComparison:
    """Test token counting and comparison."""

    def test_compare_formats_basic(self):
        data = {
            "users": [
                {"id": 1, "name": "Alice", "role": "admin"},
                {"id": 2, "name": "Bob", "role": "user"},
                {"id": 3, "name": "Carol", "role": "viewer"},
            ]
        }
        stats = compare_formats(data)

        assert stats["json_tokens"] > 0
        assert stats["toon_tokens"] > 0
        # TOON should be smaller than pretty JSON for tabular data
        assert stats["toon_tokens"] < stats["json_tokens"]
        assert stats["savings_vs_json"] > 0

    def test_compare_formats_larger_dataset(self):
        """Simulate search results - where TOON shines."""
        data = {
            "results": [
                {"path": f"/src/file{i}.py", "start_line": i * 10, "end_line": i * 10 + 5, "score": 0.9 - i * 0.05}
                for i in range(20)
            ]
        }
        stats = compare_formats(data)

        # Should see significant savings on uniform arrays
        assert stats["savings_vs_json"] > 30  # Expect 30%+ savings
        print(f"\nToken comparison for 20 search results:")
        print(f"  JSON (pretty):  {stats['json_tokens']} tokens")
        print(f"  JSON (compact): {stats['json_compact_tokens']} tokens")
        print(f"  TOON (comma):   {stats['toon_tokens']} tokens")
        print(f"  TOON (tab):     {stats['toon_tab_tokens']} tokens")
        print(f"  Savings vs JSON: {stats['savings_vs_json']}%")


class TestMCPIntegration:
    """Test TOON integration with MCP server helpers."""

    def test_should_use_toon_explicit_param(self, monkeypatch):
        """Test explicit output_format parameter takes precedence."""
        monkeypatch.delenv("TOON_ENABLED", raising=False)
        from scripts.toon_encoder import is_toon_enabled
        assert is_toon_enabled() is False

        monkeypatch.setenv("TOON_ENABLED", "1")
        assert is_toon_enabled() is True

    def test_format_results_as_toon_structure(self):
        """Test that TOON formatting produces decodable output."""
        results = [
            {"path": "/src/main.py", "start_line": 10, "end_line": 20, "score": 0.95},
            {"path": "/src/utils.py", "start_line": 5, "end_line": 15, "score": 0.87},
        ]
        toon_output = encode_search_results(results, compact=True)
        # Verify round-trip
        decoded = toon_decode(toon_output)
        assert len(decoded["results"]) == 2
        assert decoded["results"][0]["path"] == "/src/main.py"
        assert decoded["results"][1]["path"] == "/src/utils.py"

    def test_toon_replaces_results_array(self):
        """Test that TOON formatting returns a string that decodes correctly."""
        results = [{"path": "/src/main.py", "start_line": 10, "end_line": 20}]
        toon_output = encode_search_results(results, compact=True)
        assert isinstance(toon_output, str)
        decoded = toon_decode(toon_output)
        assert decoded["results"][0]["path"] == "/src/main.py"

    def test_toon_compact_mode_excludes_score(self):
        """Test that compact mode excludes score field."""
        results = [{"path": "/src/main.py", "start_line": 10, "end_line": 20, "score": 0.95}]
        output = encode_search_results(results, compact=True)
        decoded = toon_decode(output)
        assert "score" not in decoded["results"][0]

    def test_toon_full_mode_includes_score(self):
        """Test that full mode includes score field."""
        results = [{"path": "/src/main.py", "start_line": 10, "end_line": 20, "score": 0.95}]
        output = encode_search_results(results, compact=False)
        decoded = toon_decode(output)
        assert decoded["results"][0]["score"] == 0.95


class TestContextResults:
    """Test encode_context_results for mixed code/memory results."""

    def test_encode_empty_context_results(self):
        """Test empty results round-trip correctly."""
        output = encode_context_results([])
        decoded = toon_decode(output)
        assert decoded["results"] == []

    def test_encode_code_only_results(self):
        """Test encoding results with only code entries."""
        results = [
            {"source": "code", "path": "/src/main.py", "start_line": 10, "end_line": 20, "score": 0.95},
            {"source": "code", "path": "/src/utils.py", "start_line": 5, "end_line": 15, "score": 0.87},
        ]
        output = encode_context_results(results, compact=True)
        decoded = toon_decode(output)
        # Should have code section with core fields only
        assert "code" in decoded
        assert len(decoded["code"]) == 2
        assert decoded["code"][0]["path"] == "/src/main.py"
        # Score excluded in compact mode
        assert "score" not in decoded["code"][0]

    def test_encode_memory_only_results(self):
        """Test encoding results with only memory entries."""
        results = [
            {"source": "memory", "content": "API uses OAuth2", "score": 0.92},
            {"source": "memory", "content": "Database is PostgreSQL", "score": 0.85},
        ]
        output = encode_context_results(results, compact=True)
        decoded = toon_decode(output)
        assert "memory" in decoded
        assert len(decoded["memory"]) == 2
        assert decoded["memory"][0]["content"] == "API uses OAuth2"
        assert decoded["memory"][0]["score"] == 0.92

    def test_encode_mixed_code_and_memory(self):
        """Test encoding results with both code and memory entries."""
        results = [
            {"source": "code", "path": "/src/auth.py", "start_line": 100, "end_line": 150, "score": 0.95},
            {"source": "memory", "content": "Auth uses JWT tokens", "score": 0.90},
            {"source": "code", "path": "/src/jwt.py", "start_line": 20, "end_line": 40, "score": 0.88},
        ]
        output = encode_context_results(results, compact=True)
        decoded = toon_decode(output)
        assert "code" in decoded
        assert "memory" in decoded
        assert len(decoded["code"]) == 2
        assert len(decoded["memory"]) == 1
        assert decoded["code"][0]["path"] == "/src/auth.py"
        assert decoded["memory"][0]["content"] == "Auth uses JWT tokens"

    def test_encode_context_results_full_mode(self):
        """Test full mode includes additional fields."""
        results = [
            {"source": "code", "path": "/src/main.py", "start_line": 10, "end_line": 20, "score": 0.95, "symbol": "main"},
            {"source": "memory", "content": "Note about main", "score": 0.90, "id": "mem-123"},
        ]
        output = encode_context_results(results, compact=False)
        decoded = toon_decode(output)
        # Full mode should include all fields
        assert decoded["code"][0]["score"] == 0.95
        assert decoded["code"][0]["symbol"] == "main"
        assert decoded["memory"][0]["id"] == "mem-123"

    def test_encode_context_results_with_delimiter(self):
        """Test custom delimiter works correctly."""
        results = [
            {"source": "code", "path": "/src/main.py", "start_line": 10, "end_line": 20},
        ]
        output = encode_context_results(results, delimiter="\t", compact=True)
        decoded = toon_decode(output)
        assert decoded["code"][0]["path"] == "/src/main.py"


class TestFormatContextResultsAsToon:
    """Test _format_context_results_as_toon MCP helper."""

    def test_format_empty_results_adds_marker(self):
        """Test that empty results still get output_format marker."""
        from scripts.mcp_indexer_server import _format_context_results_as_toon

        response = {"results": [], "total": 0}
        result = _format_context_results_as_toon(response.copy())

        assert result["output_format"] == "toon"
        # Should decode to empty results
        decoded = toon_decode(result["results"])
        assert decoded["results"] == []

    def test_format_mixed_results(self):
        """Test formatting mixed code/memory results."""
        from scripts.mcp_indexer_server import _format_context_results_as_toon

        response = {
            "results": [
                {"source": "code", "path": "/src/api.py", "start_line": 1, "end_line": 10},
                {"source": "memory", "content": "API docs here", "score": 0.9},
            ],
            "total": 2,
        }
        result = _format_context_results_as_toon(response.copy())

        assert result["output_format"] == "toon"
        assert isinstance(result["results"], str)
        decoded = toon_decode(result["results"])
        assert "code" in decoded
        assert "memory" in decoded

    def test_format_preserves_other_fields(self):
        """Test that formatting preserves non-results fields."""
        from scripts.mcp_indexer_server import _format_context_results_as_toon

        response = {
            "results": [{"source": "code", "path": "/a.py", "start_line": 1, "end_line": 5}],
            "total": 1,
            "diag": {"code_hits": 1, "mem_hits": 0},
            "args": {"query": "test"},
        }
        result = _format_context_results_as_toon(response.copy())

        assert result["total"] == 1
        assert result["diag"] == {"code_hits": 1, "mem_hits": 0}
        assert result["args"] == {"query": "test"}


class TestDynamicFieldInclusion:
    """Test that TOON encoding doesn't drop fields."""

    def test_encode_with_snippet_field(self):
        """Test that snippet field is included in full mode."""
        results = [
            {"path": "/src/main.py", "start_line": 10, "end_line": 20,
             "score": 0.95, "snippet": "def main():\n    pass"},
        ]

        output = encode_search_results(results, compact=False)

        assert "snippet" in output
        assert "def main()" in output

    def test_encode_with_information_field(self):
        """Test that info_request's information field is included."""
        results = [
            {"path": "/src/auth.py", "start_line": 1, "end_line": 50,
             "score": 0.9, "information": "Authentication handler at /src/auth.py:1-50",
             "relevance_score": 0.9},
        ]

        output = encode_search_results(results, compact=False)

        assert "information" in output
        assert "relevance_score" in output
        assert "Authentication handler" in output

    def test_encode_with_relationships_field(self):
        """Test that relationships dict is encoded as JSON."""
        results = [
            {"path": "/src/api.py", "start_line": 10, "end_line": 30,
             "relationships": {"imports_from": ["os", "sys"], "calls": ["auth.login"]}},
        ]

        output = encode_search_results(results, compact=False)

        assert "relationships" in output
        # Nested objects become compact JSON
        assert "imports_from" in output

    def test_encode_preserves_all_custom_fields(self):
        """Test that any custom fields added by tools are preserved."""
        results = [
            {"path": "/a.py", "start_line": 1, "end_line": 5,
             "custom_field": "custom_value", "another_field": 123},
        ]

        output = encode_search_results(results, compact=False)

        assert "custom_field" in output
        assert "custom_value" in output
        assert "another_field" in output
        assert "123" in output

    def test_context_results_with_extra_memory_fields(self):
        """Test memory results preserve all fields in full mode."""
        results = [
            {"source": "memory", "content": "API note", "score": 0.9,
             "id": "mem-123", "created_at": "2024-01-01", "tags": ["api", "docs"]},
        ]

        output = encode_context_results(results, compact=False)

        assert "content" in output
        assert "id" in output
        assert "created_at" in output
        assert "tags" in output

