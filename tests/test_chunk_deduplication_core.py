"""Tests for scripts/ingest/chunk_deduplication.py - O(n log n) deduplication."""

import pytest
from scripts.ingest.chunk_deduplication import (
    normalize_content,
    get_chunk_specificity,
    deduplicate_chunks,
    deduplicate_semantic_chunks,
    CONCEPT_SPECIFICITY,
)


class TestNormalizeContent:
    """Tests for content normalization."""

    def test_strips_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        assert normalize_content("  hello  ") == "hello"
        assert normalize_content("\n\nhello\n\n") == "hello"

    def test_normalizes_line_endings(self):
        """Test that different line endings are normalized."""
        assert normalize_content("a\r\nb") == "a\nb"
        assert normalize_content("a\rb") == "a\nb"
        assert normalize_content("a\r\n\rb") == "a\n\nb"

    def test_empty_string(self):
        """Test empty string handling."""
        assert normalize_content("") == ""
        assert normalize_content("   ") == ""


class TestGetChunkSpecificity:
    """Tests for chunk specificity ranking."""

    def test_function_has_high_specificity(self):
        """Test that function chunks have high specificity."""
        chunk = {"chunk_type": "function"}
        assert get_chunk_specificity(chunk) == 4

    def test_block_has_low_specificity(self):
        """Test that block chunks have low specificity."""
        chunk = {"chunk_type": "block"}
        assert get_chunk_specificity(chunk) == 1

    def test_definition_concept_type(self):
        """Test DEFINITION concept type (from CAST+)."""
        chunk = {"chunk_type": "DEFINITION"}
        assert get_chunk_specificity(chunk) == 4

    def test_unknown_type_returns_negative(self):
        """Test unknown type returns -1."""
        chunk = {"chunk_type": "unknown_type"}
        assert get_chunk_specificity(chunk) == -1

    def test_concept_key_fallback(self):
        """Test fallback to 'concept' key."""
        chunk = {"concept": "function"}
        assert get_chunk_specificity(chunk) == 4

    def test_type_key_fallback(self):
        """Test fallback to 'type' key."""
        chunk = {"type": "class"}
        assert get_chunk_specificity(chunk) == 4

    def test_enum_value_handling(self):
        """Test handling of enum-like objects with .value."""
        from enum import Enum
        class MockConcept(Enum):
            DEFINITION = "definition"
        chunk = {"chunk_type": MockConcept.DEFINITION}
        assert get_chunk_specificity(chunk) == 4


class TestDeduplicateChunks:
    """Tests for deduplicate_chunks function."""

    def test_empty_input(self):
        """Test empty input returns empty list."""
        assert deduplicate_chunks([]) == []

    def test_no_duplicates(self):
        """Test chunks without duplicates are preserved."""
        chunks = [
            {"code": "def foo(): pass", "chunk_type": "function"},
            {"code": "def bar(): pass", "chunk_type": "function"},
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2

    def test_exact_duplicates_removed(self):
        """Test exact duplicate content is removed."""
        chunks = [
            {"code": "def foo(): pass", "chunk_type": "function"},
            {"code": "def foo(): pass", "chunk_type": "function"},
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1

    def test_keeps_higher_specificity(self):
        """Test that higher specificity chunk is kept on duplicate."""
        chunks = [
            {"code": "x = 1", "chunk_type": "block"},      # specificity 1
            {"code": "x = 1", "chunk_type": "function"},   # specificity 4
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1
        assert result[0]["chunk_type"] == "function"

    def test_vue_language_exemption(self):
        """Test Vue language is exempt from deduplication."""
        chunks = [
            {"code": "same content", "chunk_type": "block"},
            {"code": "same content", "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, language="vue")
        assert len(result) == 2

    def test_haskell_language_exemption(self):
        """Test Haskell language is exempt from deduplication."""
        chunks = [
            {"code": "same content", "chunk_type": "block"},
            {"code": "same content", "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, language="haskell")
        assert len(result) == 2

    def test_substring_removal(self):
        """Test that block substrings of definitions are removed."""
        chunks = [
            {
                "code": "def foo():\n    x = 1\n    return x",
                "chunk_type": "function",
                "start_line": 1,
                "end_line": 3,
            },
            {
                "code": "x = 1",
                "chunk_type": "block",
                "start_line": 2,
                "end_line": 2,
            },
        ]
        result = deduplicate_chunks(chunks)
        # Block should be removed as it's a substring of the function
        assert len(result) == 1
        assert result[0]["chunk_type"] == "function"

    def test_custom_content_key(self):
        """Test custom content key."""
        chunks = [
            {"text": "same", "chunk_type": "block"},
            {"text": "same", "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, content_key="text")
        assert len(result) == 1

    def test_whitespace_normalization_in_dedup(self):
        """Test that whitespace differences don't prevent dedup."""
        chunks = [
            {"code": "def foo(): pass", "chunk_type": "function"},
            {"code": "def foo(): pass  ", "chunk_type": "function"},  # trailing space
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1


class TestDeduplicateSemanticChunks:
    """Tests for deduplicate_semantic_chunks function."""

    def test_empty_input(self):
        """Test empty input returns empty list."""
        assert deduplicate_semantic_chunks([]) == []

    def test_preserves_original_objects(self):
        """Test that original objects are returned, not copies."""
        from dataclasses import dataclass
        from enum import Enum

        class ConceptType(Enum):
            DEFINITION = "definition"

        @dataclass
        class MockChunk:
            content: str
            start_line: int
            end_line: int
            concept: ConceptType

        chunk1 = MockChunk("def foo(): pass", 1, 1, ConceptType.DEFINITION)
        chunk2 = MockChunk("def bar(): pass", 2, 2, ConceptType.DEFINITION)
        
        result = deduplicate_semantic_chunks([chunk1, chunk2])
        assert len(result) == 2
        assert chunk1 in result
        assert chunk2 in result

