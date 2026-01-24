"""Domain models for code indexing.

Frozen dataclasses for immutability and hashability.
All models validate their invariants in __post_init__.

Usage:
    chunk = Chunk(
        id="abc123",
        content="def foo(): pass",
        start_line=1,
        end_line=1,
        file_path="/src/main.py",
        language="python",
        chunk_type=ChunkType.DEFINITION,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, FrozenSet

from scripts.exceptions import ValidationError


class ChunkType(str, Enum):
    """Universal chunk types for code chunking."""
    DEFINITION = "definition"
    BLOCK = "block"
    COMMENT = "comment"
    IMPORT = "import"
    STRUCTURE = "structure"
    UNKNOWN = "unknown"


class SymbolKind(str, Enum):
    """Symbol kinds for code analysis."""
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    INTERFACE = "interface"
    STRUCT = "struct"
    ENUM = "enum"
    CONSTANT = "constant"
    VARIABLE = "variable"
    TYPE_ALIAS = "type_alias"
    MODULE = "module"
    NAMESPACE = "namespace"
    PROPERTY = "property"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Position:
    """A position in a source file."""
    line: int
    column: int = 0
    byte_offset: Optional[int] = None

    def __post_init__(self) -> None:
        if self.line < 0:
            raise ValidationError("Line must be non-negative", field="line", value=self.line)
        if self.column < 0:
            raise ValidationError("Column must be non-negative", field="column", value=self.column)


@dataclass(frozen=True)
class Range:
    """A range in a source file (start inclusive, end exclusive)."""
    start: Position
    end: Position

    def __post_init__(self) -> None:
        if self.start.line > self.end.line:
            raise ValidationError(
                f"Start line ({self.start.line}) must be <= end line ({self.end.line})",
                field="range",
            )
        if self.start.line == self.end.line and self.start.column > self.end.column:
            raise ValidationError(
                f"Start column ({self.start.column}) must be <= end column ({self.end.column}) on same line",
                field="range",
            )

    @property
    def line_count(self) -> int:
        return self.end.line - self.start.line + 1


@dataclass(frozen=True)
class Symbol:
    """A code symbol (function, class, method, etc.)."""
    name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    path: Optional[str] = None
    signature: Optional[str] = None
    docstring: Optional[str] = None
    decorators: FrozenSet[str] = field(default_factory=frozenset)
    parameters: FrozenSet[str] = field(default_factory=frozenset)
    complexity: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValidationError("Symbol name cannot be empty", field="name")
        if self.start_line < 0:
            raise ValidationError("start_line must be non-negative", field="start_line", value=self.start_line)
        if self.end_line < self.start_line:
            raise ValidationError(
                f"end_line ({self.end_line}) must be >= start_line ({self.start_line})",
                field="end_line",
            )

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def full_path(self) -> str:
        return self.path or self.name


@dataclass(frozen=True)
class Chunk:
    """A code chunk for indexing."""
    id: str
    content: str
    start_line: int
    end_line: int
    file_path: str
    language: str
    chunk_type: ChunkType = ChunkType.UNKNOWN
    symbol: Optional[str] = None
    symbol_path: Optional[str] = None
    imports: FrozenSet[str] = field(default_factory=frozenset)
    calls: FrozenSet[str] = field(default_factory=frozenset)
    metadata: Dict[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError("Chunk id cannot be empty", field="id")
        if not self.content:
            raise ValidationError("Chunk content cannot be empty", field="content")
        if self.start_line < 0:
            raise ValidationError("start_line must be non-negative", field="start_line", value=self.start_line)
        if self.end_line < self.start_line:
            raise ValidationError(
                f"end_line ({self.end_line}) must be >= start_line ({self.start_line})",
                field="end_line",
            )

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(frozen=True)
class ImportRef:
    """An import reference."""
    module: str
    names: FrozenSet[str] = field(default_factory=frozenset)
    is_from_import: bool = False
    alias: Optional[str] = None
    line: Optional[int] = None


@dataclass(frozen=True)
class CallRef:
    """A function/method call reference."""
    callee: str
    caller_symbol: Optional[str] = None
    line: Optional[int] = None
    resolved_path: Optional[str] = None


@dataclass(frozen=True)
class FileAnalysis:
    """Complete analysis result for a file."""
    file_path: str
    language: str
    symbols: FrozenSet[Symbol] = field(default_factory=frozenset)
    chunks: FrozenSet[Chunk] = field(default_factory=frozenset)
    imports: FrozenSet[ImportRef] = field(default_factory=frozenset)
    calls: FrozenSet[CallRef] = field(default_factory=frozenset)
    file_hash: Optional[str] = None
    line_count: int = 0
    parse_time_ms: Optional[float] = None


@dataclass
class IndexingResult:
    """Result of indexing a file or batch of files."""
    files_processed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    chunks_indexed: int = 0
    symbols_indexed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.files_processed + self.files_skipped + self.files_failed
        if total == 0:
            return 1.0
        return self.files_processed / total


def chunk_from_dict(data: Dict[str, Any]) -> Chunk:
    """Create a Chunk from a dictionary (for interop with existing code)."""
    return Chunk(
        id=data.get("id", data.get("chunk_id", "")),
        content=data.get("content", data.get("code", data.get("text", ""))),
        start_line=data.get("start_line", data.get("start", 0)),
        end_line=data.get("end_line", data.get("end", 0)),
        file_path=data.get("file_path", data.get("path", "")),
        language=data.get("language", "unknown"),
        chunk_type=ChunkType(data.get("chunk_type", data.get("type", "unknown"))),
        symbol=data.get("symbol", data.get("name")),
        symbol_path=data.get("symbol_path"),
        imports=frozenset(data.get("imports", [])),
        calls=frozenset(data.get("calls", [])),
        metadata=data.get("metadata", {}),
    )


def symbol_from_dict(data: Dict[str, Any]) -> Symbol:
    """Create a Symbol from a dictionary (for interop with existing code)."""
    kind_str = data.get("kind", data.get("type", "unknown"))
    try:
        kind = SymbolKind(kind_str.lower())
    except ValueError:
        kind = SymbolKind.UNKNOWN

    return Symbol(
        name=data.get("name", ""),
        kind=kind,
        start_line=data.get("start_line", data.get("start", 0)),
        end_line=data.get("end_line", data.get("end", 0)),
        path=data.get("path", data.get("symbol_path")),
        signature=data.get("signature"),
        docstring=data.get("docstring"),
        decorators=frozenset(data.get("decorators", [])),
        parameters=frozenset(data.get("parameters", [])),
        complexity=data.get("complexity"),
    )


__all__ = [
    "ChunkType",
    "SymbolKind",
    "Position",
    "Range",
    "Symbol",
    "Chunk",
    "ImportRef",
    "CallRef",
    "FileAnalysis",
    "IndexingResult",
    "chunk_from_dict",
    "symbol_from_dict",
]
