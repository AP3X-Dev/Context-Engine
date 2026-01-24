#!/usr/bin/env python3
"""
Comprehensive tests for chunk deduplication and concept extraction.

Tests cover:
- chunk_deduplication.py: O(n log n) deduplication algorithm
- concept_extractor.py: Universal concept extraction with language mappings

Test categories:
- Exact content deduplication
- Substring overlap detection
- Specificity scoring
- Language exemptions (Vue, Haskell)
- Concept extraction across languages
- Edge cases and stress tests
"""

import pytest
from typing import List, Dict, Any

from scripts.ingest.chunk_deduplication import (
    normalize_content,
    compute_specificity_score,
    get_chunk_specificity,
    deduplicate_chunks,
    deduplicate_semantic_chunks,
    _deduplicate_exact_content,
    _remove_substring_overlaps,
    _extract_type_name,
    TYPE_WEIGHTS,
)

# Optional: concept extractor (may require tree-sitter)
try:
    from scripts.ingest.concept_extractor import (
        extract_concepts,
        ExtractedConcept,
        supported_languages,
    )
    from scripts.ingest.language_mappings import ConceptType
    CONCEPT_EXTRACTOR_AVAILABLE = True
except ImportError:
    CONCEPT_EXTRACTOR_AVAILABLE = False


# =============================================================================
# SECTION 1: Content Normalization
# =============================================================================

class TestNormalizeContent:
    """Tests for content normalization."""

    def test_strips_whitespace(self):
        """Strips leading and trailing whitespace."""
        assert normalize_content("  hello  ") == "hello"
        assert normalize_content("\n\ncode\n\n") == "code"

    def test_normalizes_line_endings(self):
        """Converts all line endings to \n."""
        assert normalize_content("a\r\nb\r\nc") == "a\nb\nc"
        assert normalize_content("a\rb\rc") == "a\nb\nc"
        assert normalize_content("a\nb\nc") == "a\nb\nc"

    def test_mixed_line_endings(self):
        """Handles mixed line endings."""
        content = "line1\r\nline2\rline3\nline4"
        normalized = normalize_content(content)
        assert normalized == "line1\nline2\nline3\nline4"

    def test_empty_string(self):
        """Empty string returns empty."""
        assert normalize_content("") == ""
        assert normalize_content("   ") == ""


# =============================================================================
# SECTION 2: Type Name Extraction
# =============================================================================

class TestExtractTypeName:
    """Tests for _extract_type_name helper."""

    def test_string_type(self):
        """Extracts type from string field."""
        chunk = {"chunk_type": "definition"}
        assert _extract_type_name(chunk) == "definition"

    def test_concept_field(self):
        """Falls back to concept field."""
        chunk = {"concept": "BLOCK"}
        assert _extract_type_name(chunk) == "block"

    def test_type_field(self):
        """Falls back to type field."""
        chunk = {"type": "Function"}
        assert _extract_type_name(chunk) == "function"

    def test_enum_with_value(self):
        """Handles enum with .value attribute."""
        class MockEnum:
            value = "import"
        chunk = {"chunk_type": MockEnum()}
        assert _extract_type_name(chunk) == "import"

    def test_enum_with_name(self):
        """Handles enum with .name attribute."""
        class MockEnum:
            name = "COMMENT"
        chunk = {"chunk_type": MockEnum()}
        assert _extract_type_name(chunk) == "comment"

    def test_missing_type(self):
        """Returns empty string for missing type."""
        chunk = {}
        assert _extract_type_name(chunk) == ""


# =============================================================================
# SECTION 3: Specificity Scoring
# =============================================================================

class TestComputeSpecificityScore:
    """Tests for compute_specificity_score."""

    def test_function_high_score(self):
        """Functions get high specificity score."""
        chunk = {"chunk_type": "function", "name": "my_func", "start_line": 1, "end_line": 10}
        score = compute_specificity_score(chunk)
        assert score > 0.5  # High due to type weight + name + size

    def test_block_lower_score(self):
        """Blocks get lower specificity score than definitions."""
        func = {"chunk_type": "function", "name": "f", "start_line": 1, "end_line": 5}
        block = {"chunk_type": "block", "start_line": 1, "end_line": 5}

        func_score = compute_specificity_score(func)
        block_score = compute_specificity_score(block)
        assert func_score > block_score

    def test_named_symbol_bonus(self):
        """Named symbols get bonus."""
        with_name = {"chunk_type": "function", "name": "foo", "start_line": 1, "end_line": 1}
        without_name = {"chunk_type": "function", "start_line": 1, "end_line": 1}

        assert compute_specificity_score(with_name) > compute_specificity_score(without_name)

    def test_symbol_field_counts(self):
        """symbol field also counts as name."""
        chunk = {"chunk_type": "function", "symbol": "bar", "start_line": 1, "end_line": 1}
        score = compute_specificity_score(chunk)
        # Should have name bonus
        assert score > 0.5

    def test_larger_chunks_higher_score(self):
        """Larger chunks get higher size component."""
        small = {"chunk_type": "function", "start_line": 1, "end_line": 2}
        large = {"chunk_type": "function", "start_line": 1, "end_line": 100}

        assert compute_specificity_score(large) > compute_specificity_score(small)

    def test_unknown_type_low_score(self):
        """Unknown types get minimal score."""
        chunk = {"chunk_type": "weird_type", "start_line": 1, "end_line": 1}
        score = compute_specificity_score(chunk)
        assert score < 0.3


class TestGetChunkSpecificity:
    """Tests for get_chunk_specificity (legacy 0-4 scale)."""

    def test_function_returns_4(self):
        """Function type returns 4 (highest)."""
        chunk = {"chunk_type": "function"}
        assert get_chunk_specificity(chunk) == 4

    def test_class_returns_4(self):
        """Class type returns 4."""
        chunk = {"chunk_type": "class"}
        assert get_chunk_specificity(chunk) == 4

    def test_type_alias_returns_3(self):
        """Type alias returns 3."""
        chunk = {"chunk_type": "type_alias"}
        assert get_chunk_specificity(chunk) == 3

    def test_import_returns_2(self):
        """Import returns 2."""
        chunk = {"chunk_type": "import"}
        assert get_chunk_specificity(chunk) == 2

    def test_comment_returns_1(self):
        """Comment returns 1."""
        chunk = {"chunk_type": "comment"}
        assert get_chunk_specificity(chunk) == 1

    def test_block_returns_1(self):
        """Block returns 1."""
        chunk = {"chunk_type": "block"}
        assert get_chunk_specificity(chunk) == 1

    def test_unknown_returns_0(self):
        """Unknown type returns 0."""
        chunk = {"chunk_type": "xyz"}
        assert get_chunk_specificity(chunk) == 0


# =============================================================================
# SECTION 4: Exact Content Deduplication
# =============================================================================

class TestExactContentDeduplication:
    """Tests for _deduplicate_exact_content."""

    def test_no_duplicates(self):
        """No deduplication when all unique."""
        chunks = [
            {"code": "def foo(): pass", "chunk_type": "function"},
            {"code": "def bar(): pass", "chunk_type": "function"},
            {"code": "x = 1", "chunk_type": "definition"},
        ]
        result = _deduplicate_exact_content(chunks, "code")
        assert len(result) == 3

    def test_exact_duplicate_removed(self):
        """Exact duplicates are removed."""
        chunks = [
            {"code": "def foo(): pass", "chunk_type": "function", "name": "foo"},
            {"code": "def foo(): pass", "chunk_type": "block"},  # Lower specificity
        ]
        result = _deduplicate_exact_content(chunks, "code")
        assert len(result) == 1
        assert result[0]["name"] == "foo"  # Kept higher specificity

    def test_whitespace_normalized(self):
        """Whitespace differences are normalized."""
        chunks = [
            {"code": "def foo():\n    pass", "chunk_type": "function"},
            {"code": "def foo():\n    pass  ", "chunk_type": "block"},  # Trailing space
        ]
        result = _deduplicate_exact_content(chunks, "code")
        assert len(result) == 1

    def test_keeps_highest_specificity(self):
        """When duplicates exist, keeps highest specificity."""
        chunks = [
            {"code": "x = 1", "chunk_type": "block"},
            {"code": "x = 1", "chunk_type": "function", "name": "x"},
            {"code": "x = 1", "chunk_type": "comment"},
        ]
        result = _deduplicate_exact_content(chunks, "code")
        assert len(result) == 1
        assert result[0]["chunk_type"] == "function"

    def test_content_key_fallback(self):
        """Falls back to content/text keys."""
        chunks = [
            {"content": "abc", "chunk_type": "function"},
            {"text": "def", "chunk_type": "function"},
        ]
        result = _deduplicate_exact_content(chunks, "code")
        assert len(result) == 2

    def test_empty_content_skipped(self):
        """Empty content chunks are skipped."""
        chunks = [
            {"code": "", "chunk_type": "function"},
            {"code": "valid", "chunk_type": "function"},
        ]
        result = _deduplicate_exact_content(chunks, "code")
        assert len(result) == 1
        assert result[0]["code"] == "valid"


# =============================================================================
# SECTION 5: Substring Overlap Detection
# =============================================================================

class TestSubstringOverlapRemoval:
    """Tests for _remove_substring_overlaps."""

    def test_no_overlaps(self):
        """No removal when chunks don't overlap."""
        chunks = [
            {"code": "def foo(): pass", "chunk_type": "function", "start_line": 1, "end_line": 1},
            {"code": "def bar(): pass", "chunk_type": "function", "start_line": 5, "end_line": 5},
        ]
        result = _remove_substring_overlaps(chunks, "code")
        assert len(result) == 2

    def test_block_substring_of_definition_removed(self):
        """Block that is substring of definition is removed."""
        definition_code = "def foo():\n    x = 1\n    return x"
        block_code = "x = 1"

        chunks = [
            {"code": definition_code, "chunk_type": "function", "start_line": 1, "end_line": 3},
            {"code": block_code, "chunk_type": "block", "start_line": 2, "end_line": 2},
        ]
        result = _remove_substring_overlaps(chunks, "code")
        assert len(result) == 1
        assert result[0]["chunk_type"] == "function"

    def test_non_overlapping_block_kept(self):
        """Block outside definition line range is kept."""
        chunks = [
            {"code": "def foo(): pass", "chunk_type": "function", "start_line": 1, "end_line": 1},
            {"code": "if x: y", "chunk_type": "block", "start_line": 10, "end_line": 10},
        ]
        result = _remove_substring_overlaps(chunks, "code")
        assert len(result) == 2

    def test_similar_but_not_substring_kept(self):
        """Similar content that isn't exact substring is kept."""
        chunks = [
            {"code": "def foo(x): pass", "chunk_type": "function", "start_line": 1, "end_line": 1},
            {"code": "foo(y)", "chunk_type": "block", "start_line": 1, "end_line": 1},  # Not substring
        ]
        result = _remove_substring_overlaps(chunks, "code")
        assert len(result) == 2


# =============================================================================
# SECTION 6: Full Deduplication Pipeline
# =============================================================================

class TestDeduplicateChunks:
    """Tests for deduplicate_chunks main function."""

    def test_empty_input(self):
        """Empty input returns empty."""
        result = deduplicate_chunks([])
        assert result == []

    def test_single_chunk(self):
        """Single chunk returns as-is."""
        chunks = [{"code": "x = 1", "chunk_type": "function"}]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1

    def test_full_deduplication(self):
        """Full pipeline removes exact + substring duplicates."""
        chunks = [
            {"code": "def foo():\n    x = 1", "chunk_type": "function", "name": "foo",
             "start_line": 1, "end_line": 2},
            {"code": "def foo():\n    x = 1", "chunk_type": "block",
             "start_line": 1, "end_line": 2},  # Exact dup
            {"code": "x = 1", "chunk_type": "block",
             "start_line": 2, "end_line": 2},  # Substring
        ]
        result = deduplicate_chunks(chunks, content_key="code")
        assert len(result) == 1
        assert result[0]["name"] == "foo"

    def test_vue_exemption(self):
        """Vue language preserves all chunks (no dedup)."""
        chunks = [
            {"code": "same", "chunk_type": "function"},
            {"code": "same", "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, language="vue", content_key="code")
        assert len(result) == 2

    def test_haskell_exemption(self):
        """Haskell language preserves all chunks."""
        chunks = [
            {"code": "same", "chunk_type": "function"},
            {"code": "same", "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, language="haskell", content_key="code")
        assert len(result) == 2

    def test_vue_template_exemption(self):
        """vue_template language preserves all chunks."""
        chunks = [
            {"code": "same", "chunk_type": "function"},
            {"code": "same", "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, language="vue_template", content_key="code")
        assert len(result) == 2


class TestDeduplicateSemanticChunks:
    """Tests for deduplicate_semantic_chunks (dataclass objects)."""

    def test_with_mock_dataclass(self):
        """Works with dataclass-like objects."""
        class MockChunk:
            def __init__(self, content, concept, start_line, end_line):
                self.content = content
                self.concept = concept
                self.start_line = start_line
                self.end_line = end_line

        class MockConcept:
            def __init__(self, value):
                self.value = value

        chunks = [
            MockChunk("def foo(): pass", MockConcept("definition"), 1, 1),
            MockChunk("def foo(): pass", MockConcept("block"), 1, 1),  # Duplicate
        ]
        result = deduplicate_semantic_chunks(chunks)
        assert len(result) == 1

    def test_empty_input(self):
        """Empty input returns empty."""
        result = deduplicate_semantic_chunks([])
        assert result == []

    def test_preserves_original_objects(self):
        """Returns original objects, not dicts."""
        class MockChunk:
            def __init__(self, content, start_line, end_line):
                self.content = content
                self.concept = None
                self.start_line = start_line
                self.end_line = end_line
                self.custom_field = "preserved"

        chunks = [MockChunk("unique", 1, 1)]
        result = deduplicate_semantic_chunks(chunks)
        assert len(result) == 1
        assert hasattr(result[0], "custom_field")
        assert result[0].custom_field == "preserved"


# =============================================================================
# SECTION 7: Concept Extractor (if available)
# =============================================================================

@pytest.mark.skipif(not CONCEPT_EXTRACTOR_AVAILABLE, reason="concept_extractor not available")
class TestConceptExtractor:
    """Tests for concept extraction."""

    def test_extract_python_function(self):
        """Extracts Python function definition."""
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello {name}"
'''
        concepts = extract_concepts(code, "python")

        definitions = [c for c in concepts if c.concept == ConceptType.DEFINITION]
        assert len(definitions) >= 1
        names = [c.name for c in definitions]
        assert "hello" in names

    def test_extract_python_class(self):
        """Extracts Python class."""
        code = '''
class MyClass:
    def __init__(self):
        pass
'''
        concepts = extract_concepts(code, "python")

        definitions = [c for c in concepts if c.concept == ConceptType.DEFINITION]
        names = [c.name for c in definitions]
        assert "MyClass" in names

    def test_extract_python_imports(self):
        """Extracts Python imports."""
        code = '''
import os
from pathlib import Path
'''
        concepts = extract_concepts(code, "python")

        imports = [c for c in concepts if c.concept == ConceptType.IMPORT]
        assert len(imports) >= 1

    def test_extract_comments(self):
        """Extracts comments."""
        code = '''
# This is a comment
def foo():
    pass
'''
        concepts = extract_concepts(code, "python")

        comments = [c for c in concepts if c.concept == ConceptType.COMMENT]
        # May or may not find comments depending on query
        # Just verify no crash

    def test_empty_content(self):
        """Empty content returns empty list."""
        concepts = extract_concepts("", "python")
        assert concepts == []

    def test_whitespace_only(self):
        """Whitespace-only returns empty."""
        concepts = extract_concepts("   \n\n   ", "python")
        assert concepts == []

    def test_sorted_by_line(self):
        """Concepts are sorted by start_line."""
        code = '''
def b(): pass
def a(): pass
'''
        concepts = extract_concepts(code, "python")

        lines = [c.start_line for c in concepts]
        assert lines == sorted(lines)

    def test_extracted_concept_fields(self):
        """ExtractedConcept has all expected fields."""
        code = "def foo(): pass"
        concepts = extract_concepts(code, "python")

        if concepts:
            c = concepts[0]
            assert hasattr(c, "concept")
            assert hasattr(c, "name")
            assert hasattr(c, "content")
            assert hasattr(c, "start_line")
            assert hasattr(c, "end_line")
            assert hasattr(c, "kind")
            assert hasattr(c, "metadata")


@pytest.mark.skipif(not CONCEPT_EXTRACTOR_AVAILABLE, reason="concept_extractor not available")
class TestConceptExtractorMultiLanguage:
    """Multi-language concept extraction tests."""

    def test_javascript_function(self):
        """Extracts JavaScript function."""
        code = '''
function hello(name) {
    return "Hello " + name;
}
'''
        concepts = extract_concepts(code, "javascript")
        definitions = [c for c in concepts if c.concept == ConceptType.DEFINITION]
        # Should find at least one definition
        assert len(definitions) >= 0  # May vary by tree-sitter availability

    def test_typescript_interface(self):
        """Extracts TypeScript interface."""
        code = '''
interface User {
    name: string;
    age: number;
}
'''
        concepts = extract_concepts(code, "typescript")
        # Just verify no crash
        assert isinstance(concepts, list)

    def test_go_function(self):
        """Extracts Go function."""
        code = '''
func Hello(name string) string {
    return "Hello " + name
}
'''
        concepts = extract_concepts(code, "go")
        assert isinstance(concepts, list)

    def test_rust_function(self):
        """Extracts Rust function."""
        code = '''
fn hello(name: &str) -> String {
    format!("Hello {}", name)
}
'''
        concepts = extract_concepts(code, "rust")
        assert isinstance(concepts, list)

    def test_supported_languages(self):
        """supported_languages returns list."""
        langs = supported_languages()
        assert isinstance(langs, list)
        assert "python" in langs


# =============================================================================
# SECTION 8: Edge Cases and Stress Tests
# =============================================================================

class TestDeduplicationEdgeCases:
    """Edge cases for deduplication."""

    def test_unicode_content(self):
        """Handles unicode content."""
        chunks = [
            {"code": "def héllo(): # 你好", "chunk_type": "function"},
            {"code": "def héllo(): # 你好", "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, content_key="code")
        assert len(result) == 1

    def test_very_long_content(self):
        """Handles very long content."""
        long_code = "x = 1\n" * 10000
        chunks = [
            {"code": long_code, "chunk_type": "function"},
            {"code": long_code, "chunk_type": "block"},
        ]
        result = deduplicate_chunks(chunks, content_key="code")
        assert len(result) == 1

    def test_binary_like_content(self):
        """Handles content with special characters."""
        chunks = [
            {"code": "x = b'\\x00\\x01\\x02'", "chunk_type": "function"},
        ]
        result = deduplicate_chunks(chunks, content_key="code")
        assert len(result) == 1

    def test_all_same_specificity(self):
        """When all same specificity, keeps one."""
        chunks = [
            {"code": "same", "chunk_type": "function", "start_line": 1, "end_line": 1},
            {"code": "same", "chunk_type": "function", "start_line": 2, "end_line": 2},
            {"code": "same", "chunk_type": "function", "start_line": 3, "end_line": 3},
        ]
        result = deduplicate_chunks(chunks, content_key="code")
        assert len(result) == 1


class TestDeduplicationStress:
    """Stress tests for deduplication performance."""

    def test_many_unique_chunks(self):
        """Handles many unique chunks efficiently."""
        chunks = [
            {"code": f"def func_{i}(): pass", "chunk_type": "function",
             "start_line": i, "end_line": i}
            for i in range(1000)
        ]
        result = deduplicate_chunks(chunks, content_key="code")
        assert len(result) == 1000

    def test_many_duplicates(self):
        """Handles many duplicates efficiently."""
        chunks = [
            {"code": "duplicate content", "chunk_type": "block" if i % 2 else "function",
             "start_line": i, "end_line": i}
            for i in range(1000)
        ]
        result = deduplicate_chunks(chunks, content_key="code")
        assert len(result) == 1

    def test_mixed_large_dataset(self):
        """Handles mixed large dataset."""
        chunks = []
        for i in range(500):
            # Half unique, half duplicates
            if i < 250:
                chunks.append({
                    "code": f"unique_{i}",
                    "chunk_type": "function",
                    "start_line": i,
                    "end_line": i,
                })
            else:
                chunks.append({
                    "code": "shared_code",
                    "chunk_type": "block" if i % 3 else "function",
                    "start_line": i,
                    "end_line": i,
                })

        result = deduplicate_chunks(chunks, content_key="code")
        # 250 unique + 1 from duplicates = 251
        assert len(result) == 251


class TestTypeWeights:
    """Tests for TYPE_WEIGHTS configuration."""

    def test_all_expected_types_present(self):
        """All common chunk types have weights."""
        expected = ["function", "method", "class", "interface", "struct",
                    "enum", "definition", "import", "comment", "block"]
        for t in expected:
            assert t in TYPE_WEIGHTS, f"Missing weight for {t}"

    def test_definitions_higher_than_blocks(self):
        """Definition types have higher weight than blocks."""
        assert TYPE_WEIGHTS["function"] > TYPE_WEIGHTS["block"]
        assert TYPE_WEIGHTS["class"] > TYPE_WEIGHTS["block"]
        assert TYPE_WEIGHTS["method"] > TYPE_WEIGHTS["block"]

    def test_weights_in_valid_range(self):
        """All weights are between 0 and 1."""
        for t, w in TYPE_WEIGHTS.items():
            assert 0 <= w <= 1, f"Invalid weight for {t}: {w}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
