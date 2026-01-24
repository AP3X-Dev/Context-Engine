#!/usr/bin/env python3
"""
Comprehensive tests for ingest infrastructure modules.

Tests cover:
- Domain models (models.py): validation, immutability, serialization
- Type aliases (types.py): semantic type safety
- Tree cache (tree_cache.py): LRU eviction, thread safety, invalidation
- File discovery cache (file_discovery_cache.py): TTL, mtime validation
- Exceptions (exceptions.py): hierarchy, context formatting

Test categories:
- Unit tests with edge cases
- Property-based tests with hypothesis
- Concurrency tests with ThreadPoolExecutor
- Integration tests with real filesystem
- Stress tests for cache eviction
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import FrozenInstanceError

import pytest

# Optional hypothesis import for property-based testing
try:
    from hypothesis import given, strategies as st, settings
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False
    def given(*args, **kwargs):
        def decorator(f):
            return pytest.mark.skip(reason="hypothesis not installed")(f)
        return decorator
    class st:
        @staticmethod
        def integers(*args, **kwargs): return None
        @staticmethod
        def text(*args, **kwargs): return None
    def settings(*args, **kwargs):
        def decorator(f): return f
        return decorator

from scripts.exceptions import (
    ContextEngineError,
    ValidationError,
    ParsingError,
    ChunkingError,
    EmbeddingError,
    IndexingError,
    DatabaseError,
    SearchError,
    ConfigurationError,
    ProviderError,
    CacheError,
    RateLimitError,
    TimeoutError as OperationTimeoutError,
)
from scripts.ingest.models import (
    ChunkType,
    SymbolKind,
    Position,
    Range,
    Symbol,
    Chunk,
    ImportRef,
    CallRef,
    FileAnalysis,
    IndexingResult,
    chunk_from_dict,
    symbol_from_dict,
)
from scripts.ingest.types import (
    ChunkId,
    FileId,
    LineNumber,
    ByteOffset,
    Score,
    FilePath,
    Language,
)
from scripts.ingest.tree_cache import (
    TreeCache,
    get_default_cache,
    configure_default_cache,
)
from scripts.ingest.file_discovery_cache import (
    FileDiscoveryCache,
)


# =============================================================================
# SECTION 1: Domain Models (models.py)
# =============================================================================

class TestPosition:
    """Tests for Position dataclass."""

    def test_valid_position(self):
        """Position with valid line and column."""
        pos = Position(line=10, column=5)
        assert pos.line == 10
        assert pos.column == 5
        assert pos.byte_offset is None

    def test_position_with_byte_offset(self):
        """Position with all fields."""
        pos = Position(line=1, column=0, byte_offset=0)
        assert pos.byte_offset == 0

    def test_position_zero_line_valid(self):
        """Line 0 is valid (0-indexed systems)."""
        pos = Position(line=0, column=0)
        assert pos.line == 0

    def test_position_negative_line_raises(self):
        """Negative line raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Position(line=-1, column=0)
        assert "Line must be non-negative" in str(exc_info.value)
        assert exc_info.value.field == "line"

    def test_position_negative_column_raises(self):
        """Negative column raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Position(line=0, column=-1)
        assert "Column must be non-negative" in str(exc_info.value)

    def test_position_immutable(self):
        """Position is frozen (immutable)."""
        pos = Position(line=1, column=1)
        with pytest.raises(FrozenInstanceError):
            pos.line = 2

    def test_position_hashable(self):
        """Position can be used in sets and dicts."""
        pos1 = Position(line=1, column=1)
        pos2 = Position(line=1, column=1)
        pos3 = Position(line=2, column=1)
        assert hash(pos1) == hash(pos2)
        assert {pos1, pos2, pos3} == {pos1, pos3}


class TestRange:
    """Tests for Range dataclass."""

    def test_valid_range(self):
        """Range with valid start and end."""
        r = Range(
            start=Position(line=1, column=0),
            end=Position(line=10, column=50)
        )
        assert r.line_count == 10

    def test_single_line_range(self):
        """Range spanning single line."""
        r = Range(
            start=Position(line=5, column=0),
            end=Position(line=5, column=20)
        )
        assert r.line_count == 1

    def test_range_start_after_end_raises(self):
        """Start line after end line raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Range(
                start=Position(line=10, column=0),
                end=Position(line=5, column=0)
            )
        assert "Start line" in str(exc_info.value)

    def test_range_same_line_invalid_columns(self):
        """Start column after end column on same line raises."""
        with pytest.raises(ValidationError) as exc_info:
            Range(
                start=Position(line=5, column=20),
                end=Position(line=5, column=10)
            )
        assert "column" in str(exc_info.value).lower()


class TestSymbol:
    """Tests for Symbol dataclass."""

    def test_valid_symbol(self):
        """Create a valid symbol."""
        sym = Symbol(
            name="my_function",
            kind=SymbolKind.FUNCTION,
            start_line=1,
            end_line=10,
        )
        assert sym.name == "my_function"
        assert sym.kind == SymbolKind.FUNCTION
        assert sym.line_count == 10

    def test_symbol_with_all_fields(self):
        """Symbol with all optional fields."""
        sym = Symbol(
            name="MyClass",
            kind=SymbolKind.CLASS,
            start_line=1,
            end_line=50,
            path="/src/main.py",
            signature="class MyClass(Base):",
            docstring="A test class.",
            decorators=frozenset(["@dataclass", "@frozen"]),
            parameters=frozenset(["self", "value"]),
            complexity=5,
        )
        assert sym.full_path == "/src/main.py"
        assert "@dataclass" in sym.decorators

    def test_symbol_empty_name_raises(self):
        """Empty name raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Symbol(name="", kind=SymbolKind.FUNCTION, start_line=1, end_line=1)
        assert "name cannot be empty" in str(exc_info.value)

    def test_symbol_negative_start_line_raises(self):
        """Negative start_line raises ValidationError."""
        with pytest.raises(ValidationError):
            Symbol(name="foo", kind=SymbolKind.FUNCTION, start_line=-1, end_line=1)

    def test_symbol_end_before_start_raises(self):
        """end_line before start_line raises ValidationError."""
        with pytest.raises(ValidationError):
            Symbol(name="foo", kind=SymbolKind.FUNCTION, start_line=10, end_line=5)

    def test_symbol_full_path_fallback(self):
        """full_path falls back to name when path is None."""
        sym = Symbol(name="helper", kind=SymbolKind.FUNCTION, start_line=1, end_line=1)
        assert sym.full_path == "helper"

    def test_symbol_kinds_enum(self):
        """All SymbolKind values are valid."""
        kinds = [SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CLASS,
                 SymbolKind.INTERFACE, SymbolKind.STRUCT, SymbolKind.ENUM,
                 SymbolKind.CONSTANT, SymbolKind.VARIABLE, SymbolKind.TYPE_ALIAS,
                 SymbolKind.MODULE, SymbolKind.NAMESPACE, SymbolKind.PROPERTY,
                 SymbolKind.UNKNOWN]
        for kind in kinds:
            sym = Symbol(name="test", kind=kind, start_line=1, end_line=1)
            assert sym.kind == kind


class TestChunk:
    """Tests for Chunk dataclass."""

    def test_valid_chunk(self):
        """Create a valid chunk."""
        chunk = Chunk(
            id="abc123",
            content="def foo(): pass",
            start_line=1,
            end_line=1,
            file_path="/src/main.py",
            language="python",
        )
        assert chunk.id == "abc123"
        assert chunk.chunk_type == ChunkType.UNKNOWN

    def test_chunk_with_all_fields(self):
        """Chunk with all fields populated."""
        chunk = Chunk(
            id="xyz789",
            content="class Foo:\n    pass",
            start_line=1,
            end_line=2,
            file_path="/src/main.py",
            language="python",
            chunk_type=ChunkType.DEFINITION,
            symbol="Foo",
            symbol_path="main.Foo",
            imports=frozenset(["os", "sys"]),
            calls=frozenset(["print", "open"]),
            metadata={"complexity": 1},
        )
        assert chunk.chunk_type == ChunkType.DEFINITION
        assert "os" in chunk.imports
        assert chunk.line_count == 2

    def test_chunk_empty_id_raises(self):
        """Empty id raises ValidationError."""
        with pytest.raises(ValidationError):
            Chunk(id="", content="x", start_line=1, end_line=1,
                  file_path="/a.py", language="python")

    def test_chunk_empty_content_raises(self):
        """Empty content raises ValidationError."""
        with pytest.raises(ValidationError):
            Chunk(id="a", content="", start_line=1, end_line=1,
                  file_path="/a.py", language="python")

    def test_chunk_types_enum(self):
        """All ChunkType values work."""
        for chunk_type in ChunkType:
            chunk = Chunk(
                id="test", content="x", start_line=1, end_line=1,
                file_path="/a.py", language="python", chunk_type=chunk_type
            )
            assert chunk.chunk_type == chunk_type


class TestChunkFromDict:
    """Tests for chunk_from_dict interop function."""

    def test_standard_keys(self):
        """Convert dict with standard keys."""
        data = {
            "id": "chunk1",
            "content": "def foo(): pass",
            "start_line": 1,
            "end_line": 1,
            "file_path": "/a.py",
            "language": "python",
            "chunk_type": "definition",
        }
        chunk = chunk_from_dict(data)
        assert chunk.id == "chunk1"
        assert chunk.chunk_type == ChunkType.DEFINITION

    def test_alternate_keys(self):
        """Convert dict with alternate keys (chunk_id, code, start, end)."""
        data = {
            "chunk_id": "c2",
            "code": "class Bar: pass",
            "start": 5,
            "end": 5,
            "path": "/b.py",
            "language": "python",
            "type": "definition",
        }
        chunk = chunk_from_dict(data)
        assert chunk.id == "c2"
        assert chunk.content == "class Bar: pass"
        assert chunk.start_line == 5

    def test_missing_keys_use_defaults(self):
        """Missing keys use reasonable defaults."""
        data = {"id": "x", "content": "y", "file_path": "/z.py"}
        chunk = chunk_from_dict(data)
        assert chunk.language == "unknown"
        assert chunk.chunk_type == ChunkType.UNKNOWN


class TestSymbolFromDict:
    """Tests for symbol_from_dict interop function."""

    def test_standard_keys(self):
        """Convert dict with standard keys."""
        data = {
            "name": "my_func",
            "kind": "function",
            "start_line": 1,
            "end_line": 10,
        }
        sym = symbol_from_dict(data)
        assert sym.name == "my_func"
        assert sym.kind == SymbolKind.FUNCTION

    def test_unknown_kind_fallback(self):
        """Unknown kind falls back to UNKNOWN."""
        data = {"name": "x", "kind": "weird_kind", "start_line": 1, "end_line": 1}
        sym = symbol_from_dict(data)
        assert sym.kind == SymbolKind.UNKNOWN

    def test_case_insensitive_kind(self):
        """Kind matching is case-insensitive."""
        data = {"name": "x", "kind": "FUNCTION", "start_line": 1, "end_line": 1}
        sym = symbol_from_dict(data)
        assert sym.kind == SymbolKind.FUNCTION


class TestFileAnalysis:
    """Tests for FileAnalysis dataclass."""

    def test_empty_analysis(self):
        """Create empty file analysis."""
        analysis = FileAnalysis(file_path="/a.py", language="python")
        assert analysis.symbols == frozenset()
        assert analysis.chunks == frozenset()
        assert analysis.line_count == 0

    def test_analysis_with_data(self):
        """Create file analysis with symbols and chunks."""
        sym = Symbol(name="foo", kind=SymbolKind.FUNCTION, start_line=1, end_line=5)
        chunk = Chunk(id="c1", content="def foo(): pass", start_line=1, end_line=1,
                      file_path="/a.py", language="python")
        analysis = FileAnalysis(
            file_path="/a.py",
            language="python",
            symbols=frozenset([sym]),
            chunks=frozenset([chunk]),
            line_count=100,
            parse_time_ms=15.5,
        )
        assert len(analysis.symbols) == 1
        assert analysis.parse_time_ms == 15.5


class TestIndexingResult:
    """Tests for IndexingResult dataclass."""

    def test_empty_result(self):
        """Empty result has 100% success rate."""
        result = IndexingResult()
        assert result.success_rate == 1.0

    def test_success_rate_calculation(self):
        """Success rate calculated correctly."""
        result = IndexingResult(files_processed=8, files_skipped=1, files_failed=1)
        assert result.success_rate == 0.8

    def test_result_is_mutable(self):
        """IndexingResult is mutable (not frozen)."""
        result = IndexingResult()
        result.files_processed = 10
        result.errors.append("Some error")
        assert result.files_processed == 10
        assert len(result.errors) == 1


# =============================================================================
# SECTION 2: Property-Based Tests (with hypothesis)
# =============================================================================

@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestModelPropertiesHypothesis:
    """Property-based tests for domain models."""

    @given(st.integers(min_value=0, max_value=10000),
           st.integers(min_value=0, max_value=1000))
    @settings(max_examples=100)
    def test_position_valid_range(self, line, column):
        """Any non-negative line/column produces valid Position."""
        pos = Position(line=line, column=column)
        assert pos.line >= 0
        assert pos.column >= 0

    @given(st.integers(min_value=0, max_value=1000),
           st.integers(min_value=0, max_value=1000))
    @settings(max_examples=50)
    def test_range_line_count_property(self, start, delta):
        """Range line_count is always end - start + 1."""
        end = start + delta
        r = Range(
            start=Position(line=start, column=0),
            end=Position(line=end, column=0)
        )
        assert r.line_count == delta + 1

    @given(st.text(min_size=1, max_size=100, alphabet="abcdefghijklmnopqrstuvwxyz_"))
    @settings(max_examples=50)
    def test_symbol_name_preserved(self, name):
        """Symbol name is preserved exactly."""
        sym = Symbol(name=name, kind=SymbolKind.FUNCTION, start_line=1, end_line=1)
        assert sym.name == name


# =============================================================================
# SECTION 3: Exception Hierarchy (exceptions.py)
# =============================================================================

class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_base_exception_inheritance(self):
        """All exceptions inherit from ContextEngineError."""
        exceptions = [
            ValidationError, ParsingError, ChunkingError, EmbeddingError,
            IndexingError, DatabaseError, SearchError, ConfigurationError,
            ProviderError, CacheError, RateLimitError, OperationTimeoutError,
        ]
        for exc_class in exceptions:
            assert issubclass(exc_class, ContextEngineError)

    def test_rate_limit_inherits_provider(self):
        """RateLimitError inherits from ProviderError."""
        assert issubclass(RateLimitError, ProviderError)


class TestExceptionContext:
    """Tests for exception context formatting."""

    def test_base_exception_str(self):
        """Base exception formats message correctly."""
        e = ContextEngineError("Something failed")
        assert str(e) == "Something failed"

    def test_exception_with_context(self):
        """Exception with context includes it in str()."""
        e = ContextEngineError("Failed", context={"file": "test.py", "line": 42})
        s = str(e)
        assert "Failed" in s
        assert "file=test.py" in s
        assert "line=42" in s

    def test_validation_error_context(self):
        """ValidationError includes field and value in context."""
        e = ValidationError("Invalid value", field="age", value=-5)
        s = str(e)
        assert "field=age" in s
        assert "-5" in s

    def test_parsing_error_context(self):
        """ParsingError includes file, language, and line."""
        e = ParsingError("Syntax error", file_path="/test.py", language="python", line=10)
        s = str(e)
        assert "file=/test.py" in s
        assert "language=python" in s
        assert "line=10" in s

    def test_rate_limit_error_retry_after(self):
        """RateLimitError includes retry_after and status 429."""
        e = RateLimitError("Rate limited", provider="openai", retry_after=30.0)
        assert e.status_code == 429
        assert e.retry_after == 30.0
        assert "retry_after=30.0" in str(e)

    def test_search_error_truncates_long_query(self):
        """SearchError truncates very long queries in context."""
        long_query = "x" * 200
        e = SearchError("Search failed", query=long_query)
        assert len(e.context.get("query", "")) <= 100


class TestExceptionAttributes:
    """Tests for exception-specific attributes."""

    def test_validation_error_attributes(self):
        """ValidationError stores field and value."""
        e = ValidationError("Bad input", field="name", value="")
        assert e.field == "name"
        assert e.value == ""

    def test_embedding_error_attributes(self):
        """EmbeddingError stores provider, model, batch_size."""
        e = EmbeddingError("Embed failed", provider="openai", model="ada", batch_size=100)
        assert e.provider == "openai"
        assert e.model == "ada"
        assert e.batch_size == 100

    def test_indexing_error_attributes(self):
        """IndexingError stores collection, file_path, point_count."""
        e = IndexingError("Index failed", collection="test_coll", point_count=500)
        assert e.collection == "test_coll"
        assert e.point_count == 500


# =============================================================================
# SECTION 4: Tree Cache (tree_cache.py)
# =============================================================================

class TestTreeCacheBasic:
    """Basic TreeCache functionality tests."""

    def test_cache_miss(self, tmp_path):
        """Cache returns None for uncached files."""
        cache = TreeCache(max_entries=10)
        result = cache.get(tmp_path / "nonexistent.py")
        assert result is None
        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_cache_put_get(self, tmp_path):
        """Put and get returns cached tree."""
        cache = TreeCache(max_entries=10)
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo(): pass")
        fake_tree = {"type": "module", "children": []}
        cache.put(test_file, fake_tree)
        result = cache.get(test_file)
        assert result == fake_tree
        stats = cache.get_stats()
        assert stats["hits"] == 1

    def test_cache_invalidation_on_mtime_change(self, tmp_path):
        """Cache invalidates when file mtime changes."""
        cache = TreeCache(max_entries=10)
        test_file = tmp_path / "test.py"
        test_file.write_text("v1")
        cache.put(test_file, {"version": 1})
        assert cache.get(test_file) == {"version": 1}
        time.sleep(0.01)
        test_file.write_text("v2")
        result = cache.get(test_file)
        assert result is None
        stats = cache.get_stats()
        assert stats["invalidations"] == 1

    def test_cache_invalidation_on_size_change(self, tmp_path):
        """Cache invalidates when file size changes."""
        cache = TreeCache(max_entries=10)
        test_file = tmp_path / "test.py"
        test_file.write_text("short")
        cache.put(test_file, {"v": 1})
        original_mtime = test_file.stat().st_mtime
        test_file.write_text("much longer content here")
        os.utime(test_file, (original_mtime, original_mtime))
        result = cache.get(test_file)
        assert result is None

    def test_explicit_invalidate(self, tmp_path):
        """Explicit invalidate() removes entry."""
        cache = TreeCache(max_entries=10)
        test_file = tmp_path / "test.py"
        test_file.write_text("content")
        cache.put(test_file, {"tree": True})
        assert cache.get(test_file) is not None
        removed = cache.invalidate(test_file)
        assert removed is True
        assert cache.get(test_file) is None
        removed_again = cache.invalidate(test_file)
        assert removed_again is False


class TestTreeCacheLRU:
    """LRU eviction tests for TreeCache."""

    def test_lru_eviction_by_count(self, tmp_path):
        """Oldest entries evicted when max_entries exceeded."""
        cache = TreeCache(max_entries=3)
        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"content {i}")
            files.append(f)
            cache.put(f, {"idx": i})
        assert cache.get(files[0]) is None
        assert cache.get(files[1]) is None
        assert cache.get(files[2]) == {"idx": 2}
        assert cache.get(files[3]) == {"idx": 3}
        assert cache.get(files[4]) == {"idx": 4}
        stats = cache.get_stats()
        assert stats["evictions"] == 2

    def test_lru_access_updates_order(self, tmp_path):
        """Accessing entry moves it to end (most recent)."""
        cache = TreeCache(max_entries=3)
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"c{i}")
            files.append(f)
            cache.put(f, {"i": i})
        cache.get(files[0])
        new_file = tmp_path / "new.py"
        new_file.write_text("new")
        cache.put(new_file, {"new": True})
        assert cache.get(files[0]) == {"i": 0}
        assert cache.get(files[1]) is None
        assert cache.get(files[2]) == {"i": 2}


class TestTreeCacheMemoryLimit:
    """Memory limit tests for TreeCache."""

    def test_memory_limit_eviction(self, tmp_path):
        """Entries evicted when memory limit exceeded."""
        cache = TreeCache(max_entries=100, max_memory_mb=1)
        files = []
        for i in range(5):
            f = tmp_path / f"big{i}.py"
            f.write_text("x" * (500 * 1024))
            files.append(f)
            cache.put(f, {"big": i})
        stats = cache.get_stats()
        assert stats["evictions"] > 0
        assert stats["estimated_memory_mb"] <= 1.5


class TestTreeCacheConcurrency:
    """Thread safety tests for TreeCache."""

    def test_concurrent_put_get(self, tmp_path):
        """Concurrent put/get operations don't corrupt cache."""
        cache = TreeCache(max_entries=50)
        errors = []

        def worker(worker_id):
            try:
                for i in range(20):
                    f = tmp_path / f"worker{worker_id}_file{i}.py"
                    f.write_text(f"content_{worker_id}_{i}")
                    cache.put(f, {"w": worker_id, "i": i})
                    result = cache.get(f)
                    if result is not None and result != {"w": worker_id, "i": i}:
                        errors.append(f"Mismatch: {result}")
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(8)]
            for f in as_completed(futures):
                f.result()
        assert len(errors) == 0, f"Errors: {errors}"

    def test_concurrent_invalidate(self, tmp_path):
        """Concurrent invalidation is safe."""
        cache = TreeCache(max_entries=100)
        files = []
        for i in range(50):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"c{i}")
            files.append(f)
            cache.put(f, {"i": i})

        def invalidator(file_path):
            cache.invalidate(file_path)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(invalidator, f) for f in files]
            for fut in as_completed(futures):
                fut.result()
        for f in files:
            assert cache.get(f) is None


class TestTreeCacheHelpers:
    """Tests for TreeCache helper methods."""

    def test_get_for_comparison_returns_stale(self, tmp_path):
        """get_for_comparison returns cached tree even if stale."""
        cache = TreeCache(max_entries=10)
        test_file = tmp_path / "test.py"
        test_file.write_text("v1")
        cache.put(test_file, {"old": True})
        time.sleep(0.01)
        test_file.write_text("v2")
        assert cache.get(test_file) is None
        cache.put(test_file, {"new": True})
        time.sleep(0.01)
        test_file.write_text("v3")
        result = cache.get_for_comparison(test_file)
        assert result == {"new": True}

    def test_cleanup_stale_entries(self, tmp_path):
        """cleanup_stale_entries removes outdated entries."""
        cache = TreeCache(max_entries=10)
        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"c{i}")
            files.append(f)
            cache.put(f, {"i": i})
        time.sleep(0.01)
        for f in files[:2]:
            f.write_text("modified")
        removed = cache.cleanup_stale_entries()
        assert removed == 2
        stats = cache.get_stats()
        assert stats["entries"] == 3

    def test_get_cache_info(self, tmp_path):
        """get_cache_info returns detailed entry info."""
        cache = TreeCache(max_entries=10)
        test_file = tmp_path / "test.py"
        test_file.write_text("content")
        cache.put(test_file, {"tree": True})
        cache.get(test_file)
        cache.get(test_file)
        info = cache.get_cache_info(test_file)
        assert info is not None
        assert info["hit_count"] == 2
        assert info["is_valid"] is True
        assert "cached_mtime" in info

    def test_clear(self, tmp_path):
        """clear() removes all entries."""
        cache = TreeCache(max_entries=10)
        for i in range(5):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"c{i}")
            cache.put(f, {"i": i})
        cache.clear()
        assert cache.get_stats()["entries"] == 0


class TestTreeCacheGlobal:
    """Tests for global cache functions."""

    def test_get_default_cache_singleton(self):
        """get_default_cache returns same instance."""
        cache1 = get_default_cache()
        cache2 = get_default_cache()
        assert cache1 is cache2

    def test_configure_default_cache(self):
        """configure_default_cache creates new instance."""
        old_cache = get_default_cache()
        new_cache = configure_default_cache(max_entries=500, max_memory_mb=100)
        assert new_cache is not old_cache
        assert new_cache.max_entries == 500


# =============================================================================
# SECTION 5: File Discovery Cache (file_discovery_cache.py)
# =============================================================================

class TestFileDiscoveryCacheBasic:
    """Basic FileDiscoveryCache tests."""

    def test_cache_miss_discovery(self, tmp_path):
        """First call discovers files (cache miss)."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "c.js").write_text("c")
        files = cache.get_files(tmp_path, patterns=["*.py"])
        assert len(files) == 2
        assert any(f.name == "a.py" for f in files)
        assert any(f.name == "b.py" for f in files)
        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_cache_hit(self, tmp_path):
        """Second call with same params is cache hit."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        (tmp_path / "a.py").write_text("a")
        cache.get_files(tmp_path, patterns=["*.py"])
        cache.get_files(tmp_path, patterns=["*.py"])
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_exclude_patterns(self, tmp_path):
        """Exclude patterns filter results."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "test_a.py").write_text("test")
        files = cache.get_files(
            tmp_path,
            patterns=["*.py"],
            exclude_patterns=["test_*.py"]
        )
        assert len(files) == 1
        assert files[0].name == "a.py"


class TestFileDiscoveryCacheTTL:
    """TTL expiration tests for FileDiscoveryCache."""

    def test_ttl_expiration(self, tmp_path):
        """Cache expires after TTL."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=1)
        (tmp_path / "a.py").write_text("a")
        cache.get_files(tmp_path, patterns=["*.py"])
        assert cache.get_stats()["hits"] == 0
        time.sleep(1.1)
        cache.get_files(tmp_path, patterns=["*.py"])
        stats = cache.get_stats()
        assert stats["misses"] == 2


class TestFileDiscoveryCacheMtime:
    """Mtime-based invalidation tests."""

    def test_mtime_invalidation(self, tmp_path):
        """Cache invalidates when directory mtime changes."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        (tmp_path / "a.py").write_text("a")
        cache.get_files(tmp_path, patterns=["*.py"])
        time.sleep(0.01)
        (tmp_path / "b.py").write_text("b")
        files = cache.get_files(tmp_path, patterns=["*.py"])
        assert len(files) == 2
        stats = cache.get_stats()
        assert stats["invalidations"] == 1

    def test_invalidate_directory(self, tmp_path):
        """invalidate_directory removes matching entries."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        sub1 = tmp_path / "sub1"
        sub1.mkdir()
        (sub1 / "a.py").write_text("a")
        sub2 = tmp_path / "sub2"
        sub2.mkdir()
        (sub2 / "b.py").write_text("b")
        cache.get_files(sub1, patterns=["*.py"])
        cache.get_files(sub2, patterns=["*.py"])
        assert cache.get_stats()["cache_size"] == 2
        removed = cache.invalidate_directory(sub1)
        assert removed == 1
        assert cache.get_stats()["cache_size"] == 1


class TestFileDiscoveryCacheLRU:
    """LRU eviction tests for FileDiscoveryCache."""

    def test_lru_eviction(self, tmp_path):
        """Oldest entries evicted when max_entries exceeded."""
        cache = FileDiscoveryCache(max_entries=3, ttl_seconds=300)
        for i in range(5):
            d = tmp_path / f"dir{i}"
            d.mkdir()
            (d / "file.py").write_text("x")
            cache.get_files(d, patterns=["*.py"])
        stats = cache.get_stats()
        assert stats["cache_size"] == 3
        assert stats["evictions"] == 2


class TestFileDiscoveryCachePatterns:
    """Pattern matching tests."""

    def test_multiple_patterns(self, tmp_path):
        """Multiple patterns are OR'd together."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.js").write_text("b")
        (tmp_path / "c.txt").write_text("c")
        files = cache.get_files(tmp_path, patterns=["*.py", "*.js"])
        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"a.py", "b.js"}

    def test_recursive_pattern(self, tmp_path):
        """Recursive glob patterns work."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        files = cache.get_files(tmp_path, patterns=["**/*.py"])
        assert len(files) == 2

    def test_deduplication(self, tmp_path):
        """Overlapping patterns don't create duplicates."""
        cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        (tmp_path / "test.py").write_text("x")
        files = cache.get_files(tmp_path, patterns=["*.py", "test.*"])
        assert len(files) == 1


# =============================================================================
# SECTION 6: Type Aliases (types.py)
# =============================================================================

class TestTypeAliases:
    """Tests for type aliases semantic safety."""

    def test_newtype_creates_distinct_types(self):
        """NewType creates logically distinct types."""
        chunk_id: ChunkId = ChunkId("chunk123")
        file_id: FileId = FileId("file456")
        assert isinstance(chunk_id, str)
        assert isinstance(file_id, str)
        assert chunk_id == "chunk123"
        assert file_id == "file456"

    def test_numeric_types(self):
        """Numeric NewTypes work correctly."""
        line: LineNumber = LineNumber(42)
        offset: ByteOffset = ByteOffset(1024)
        score: Score = Score(0.95)
        assert line == 42
        assert offset == 1024
        assert abs(score - 0.95) < 0.001

    def test_path_types(self):
        """Path-related NewTypes work."""
        path: FilePath = FilePath("/src/main.py")
        lang: Language = Language("python")
        assert path.endswith(".py")
        assert lang == "python"


# =============================================================================
# SECTION 7: Integration Tests
# =============================================================================

class TestCacheIntegration:
    """Integration tests using multiple caches together."""

    def test_tree_and_file_cache_together(self, tmp_path):
        """TreeCache and FileDiscoveryCache work together."""
        tree_cache = TreeCache(max_entries=10)
        file_cache = FileDiscoveryCache(max_entries=10, ttl_seconds=300)
        for i in range(5):
            (tmp_path / f"file{i}.py").write_text(f"def func{i}(): pass")
        files = file_cache.get_files(tmp_path, patterns=["*.py"])
        assert len(files) == 5
        for f in files:
            tree_cache.put(f, {"parsed": True, "path": str(f)})
        for f in files:
            assert tree_cache.get(f) is not None
        time.sleep(0.01)
        files[0].write_text("modified content")
        assert tree_cache.get(files[0]) is None
        assert tree_cache.get(files[1]) is not None
        new_files = file_cache.get_files(tmp_path, patterns=["*.py"])
        assert len(new_files) == 5


class TestExceptionInPipeline:
    """Test exceptions in realistic pipeline scenarios."""

    def test_exception_chain(self):
        """Exceptions can be chained for context."""
        try:
            try:
                raise ParsingError("Tree-sitter failed", file_path="/bad.py", language="python")
            except ParsingError as pe:
                raise IndexingError(
                    f"Could not index file: {pe}",
                    file_path=pe.file_path,
                ) from pe
        except IndexingError as ie:
            assert "Tree-sitter failed" in str(ie.__cause__)
            assert ie.file_path == "/bad.py"


# =============================================================================
# SECTION 8: Stress Tests
# =============================================================================

class TestStress:
    """Stress tests for cache behavior under load."""

    def test_high_volume_cache_operations(self, tmp_path):
        """Cache handles high volume of operations."""
        cache = TreeCache(max_entries=100)
        files = []
        for i in range(500):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"content_{i}")
            files.append(f)
        for i, f in enumerate(files):
            cache.put(f, {"idx": i})
        stats = cache.get_stats()
        assert stats["entries"] == 100
        assert stats["evictions"] == 400

    def test_rapid_invalidation_cycle(self, tmp_path):
        """Rapid put/invalidate cycles don't cause issues."""
        cache = TreeCache(max_entries=50)
        test_file = tmp_path / "test.py"
        test_file.write_text("initial")
        for i in range(1000):
            cache.put(test_file, {"iteration": i})
            cache.invalidate(test_file)
        assert cache.get(test_file) is None
        stats = cache.get_stats()
        assert stats["invalidations"] == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
