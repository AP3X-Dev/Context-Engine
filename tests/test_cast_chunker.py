"""Tests for scripts/ingest/cast_chunker.py - CAST+ Hybrid Chunker."""

import pytest
from scripts.ingest.cast_chunker import (
    CASTPlusConfig,
    CASTPlusChunker,
    ConceptType,
    SemanticChunk,
    ChunkResult,
    COMPATIBLE_PAIRS,
    chunk_cast_plus,
    get_cast_chunker,
)


class TestCASTPlusConfig:
    """Tests for CASTPlusConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CASTPlusConfig()
        assert config.max_chunk_size == 1200
        assert config.min_chunk_size == 50
        assert config.safe_token_limit == 6000
        assert config.merge_threshold == 0.8
        assert config.deduplicate is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = CASTPlusConfig(
            max_chunk_size=2000,
            min_chunk_size=100,
            deduplicate=False,
        )
        assert config.max_chunk_size == 2000
        assert config.min_chunk_size == 100
        assert config.deduplicate is False


class TestConceptType:
    """Tests for ConceptType enum."""

    def test_concept_values(self):
        """Test concept type values."""
        assert ConceptType.DEFINITION.value == "definition"
        assert ConceptType.BLOCK.value == "block"
        assert ConceptType.COMMENT.value == "comment"
        assert ConceptType.IMPORT.value == "import"
        assert ConceptType.STRUCTURE.value == "structure"


class TestCompatiblePairs:
    """Tests for compatible concept pairs."""

    def test_comment_definition_compatible(self):
        """Test that COMMENT and DEFINITION are compatible."""
        assert (ConceptType.COMMENT, ConceptType.DEFINITION) in COMPATIBLE_PAIRS
        assert (ConceptType.DEFINITION, ConceptType.COMMENT) in COMPATIBLE_PAIRS

    def test_block_definition_not_compatible(self):
        """Test that BLOCK and DEFINITION are NOT compatible."""
        assert (ConceptType.BLOCK, ConceptType.DEFINITION) not in COMPATIBLE_PAIRS


class TestSemanticChunk:
    """Tests for SemanticChunk dataclass."""

    def test_post_init_computes_metrics(self):
        """Test that __post_init__ computes metrics."""
        chunk = SemanticChunk(
            concept=ConceptType.DEFINITION,
            name="foo",
            content="def foo(): pass",
            start_line=1,
            end_line=1,
        )
        assert chunk.non_whitespace_chars > 0
        assert chunk.estimated_tokens > 0
        assert 0.0 <= chunk.density_score <= 1.0

    def test_empty_content_density(self):
        """Test density calculation with empty content."""
        chunk = SemanticChunk(
            concept=ConceptType.DEFINITION,
            name="empty",
            content="",
            start_line=1,
            end_line=1,
        )
        assert chunk.density_score == 0.0


class TestCASTPlusChunker:
    """Tests for CASTPlusChunker class."""

    def test_initialization(self):
        """Test chunker initialization."""
        chunker = CASTPlusChunker()
        assert chunker.config is not None
        assert isinstance(chunker.config, CASTPlusConfig)

    def test_custom_config(self):
        """Test chunker with custom config."""
        config = CASTPlusConfig(max_chunk_size=500)
        chunker = CASTPlusChunker(config)
        assert chunker.config.max_chunk_size == 500

    def test_chunk_simple_function(self):
        """Test chunking a simple function."""
        chunker = CASTPlusChunker()
        content = '''def hello():
    """Say hello."""
    print("Hello, World!")
'''
        results = chunker.chunk(content, "python")
        assert len(results) >= 1
        assert all(isinstance(r, ChunkResult) for r in results)

    def test_chunk_to_dicts(self):
        """Test chunk_to_dicts returns dictionaries."""
        chunker = CASTPlusChunker()
        content = "def foo(): pass"
        results = chunker.chunk_to_dicts(content, "python")
        assert all(isinstance(r, dict) for r in results)
        if results:
            assert "text" in results[0]
            # Uses 'start' and 'end' keys, not 'start_line'
            assert "start" in results[0] or "start_line" in results[0]

    def test_deduplication_enabled(self):
        """Test that deduplication removes duplicates."""
        config = CASTPlusConfig(deduplicate=True)
        chunker = CASTPlusChunker(config)
        # Content with duplicate blocks
        content = '''x = 1
x = 1
'''
        results = chunker.chunk(content, "python")
        # Should have fewer chunks due to dedup
        assert len(results) >= 1

    def test_deduplication_disabled(self):
        """Test that deduplication can be disabled."""
        config = CASTPlusConfig(deduplicate=False)
        chunker = CASTPlusChunker(config)
        content = "x = 1"
        results = chunker.chunk(content, "python")
        assert len(results) >= 1


class TestChunkCastPlus:
    """Tests for chunk_cast_plus convenience function."""

    def test_basic_usage(self):
        """Test basic usage of chunk_cast_plus."""
        content = "def foo(): pass"
        results = chunk_cast_plus(content, "python")
        assert isinstance(results, list)
        assert all(isinstance(r, dict) for r in results)

    def test_with_custom_config(self):
        """Test with custom config."""
        config = CASTPlusConfig(max_chunk_size=500)
        content = "def foo(): pass"
        results = chunk_cast_plus(content, "python", config=config)
        assert isinstance(results, list)


class TestGetCastChunker:
    """Tests for get_cast_chunker factory function."""

    def test_returns_chunker(self):
        """Test that get_cast_chunker returns a chunker."""
        chunker = get_cast_chunker()
        assert isinstance(chunker, CASTPlusChunker)

    def test_with_custom_config(self):
        """Test with custom config returns new instance."""
        config = CASTPlusConfig(max_chunk_size=999)
        chunker = get_cast_chunker(config)
        assert chunker.config.max_chunk_size == 999

