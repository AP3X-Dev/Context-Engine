#!/usr/bin/env python3
"""
ingest/search_chunker.py - Search-Optimized Semantic Chunker (SOSC).

A novel chunking approach designed specifically for code search engines.
Inspired by cAST (ChunkHound) but optimized for Context-Engine's needs.

Key Design Principles:
1. NO context padding - imports/class signatures stored as metadata only
2. Symbol-boundary respect - complete functions/classes when possible
3. Concept-aware merging - only merge semantically compatible types
4. Rich metadata extraction - parent, kind, concept, decorators
5. Minified code handling - smart split at syntax boundaries
6. Deduplication - prevent indexing identical code twice

What makes SOSC different from cAST:
- Uses Context-Engine's 32 language mappings (richer metadata)
- Optimized for embedding quality (clean text, no padding)
- Integrates with existing symbol graph
- Concept types guide merging, not just splitting

What makes SOSC different from SDC:
- Concept-aware merging (DEFINITION, BLOCK, COMMENT, IMPORT, STRUCTURE)
- Emergency splitting for minified code
- Nested chunk prevention
- Deduplication built-in
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Set, Tuple

import hashlib
from typing import TYPE_CHECKING

_XXHASH_AVAILABLE = False
try:
    import xxhash  # type: ignore
    _XXHASH_AVAILABLE = True
except ImportError:
    pass


def _fast_hash(text: str) -> str:
    data = text.encode()
    if _XXHASH_AVAILABLE:
        return xxhash.xxh64(data).hexdigest()[:16]  # type: ignore
    return hashlib.md5(data).hexdigest()[:16]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ConceptType(Enum):
    """Universal semantic concepts (inspired by cAST)."""
    DEFINITION = "definition"  # Functions, classes, types, constants
    BLOCK = "block"            # Control flow blocks, scoped regions
    COMMENT = "comment"        # Comments, docstrings
    IMPORT = "import"          # Import/include statements
    STRUCTURE = "structure"    # File-level structure (headers, sections)


# Compatible concept pairs that CAN be merged
COMPATIBLE_MERGE_PAIRS: Set[Tuple[ConceptType, ConceptType]] = {
    (ConceptType.COMMENT, ConceptType.DEFINITION),  # Docstring + function
    (ConceptType.DEFINITION, ConceptType.COMMENT),  # Function + trailing comment
    (ConceptType.BLOCK, ConceptType.COMMENT),       # Code block + inline comment
    (ConceptType.COMMENT, ConceptType.BLOCK),       # Comment + code block
}


@dataclass
class SOSCConfig:
    """Configuration for Search-Optimized Semantic Chunker."""
    # Size limits (non-whitespace characters, like cAST)
    max_chunk_chars: int = 1200      # Maximum non-whitespace chars
    min_chunk_chars: int = 50        # Minimum to avoid tiny fragments
    
    # Merge behavior
    merge_threshold: float = 0.8     # Merge if combined < threshold * max
    max_merge_gap_lines: int = 5     # Max blank lines for same-concept merge
    comment_merge_gap: int = 1       # Stricter gap for comment merging
    
    # Token safety (for embedding API limits)
    safe_token_limit: int = 6000     # Conservative limit under 8191
    chars_per_token: float = 3.5     # Conservative estimation
    
    # Features
    deduplicate: bool = True         # Remove identical content chunks
    prevent_nested_merge: bool = True  # Don't merge nested ranges
    
    # Emergency split characters for minified code
    split_chars: str = ";}{,"        # Priority order for splitting


@dataclass
class SemanticChunk:
    """A semantic code chunk with rich metadata."""
    concept: ConceptType
    name: str
    content: str
    start_line: int
    end_line: int
    
    # Metadata (stored, not embedded)
    kind: str = ""                   # function, class, method, etc.
    parent: Optional[str] = None     # Parent symbol name
    parent_kind: Optional[str] = None
    signature: Optional[str] = None
    docstring: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    is_async: bool = False
    visibility: Optional[str] = None  # public, private, protected
    
    # Computed
    content_hash: str = ""           # For deduplication
    
    def __post_init__(self):
        if not self.content_hash:
            normalized = re.sub(r'\s+', ' ', self.content.strip())
            self.content_hash = _fast_hash(normalized)
    
    @property
    def non_whitespace_chars(self) -> int:
        """Count non-whitespace characters (cAST metric)."""
        return len(re.sub(r'\s', '', self.content))
    
    @property
    def estimated_tokens(self) -> int:
        """Estimate token count conservatively."""
        return int(self.non_whitespace_chars / 3.5)


@dataclass 
class ChunkResult:
    """Result compatible with existing pipeline."""
    text: str
    start: int
    end: int
    symbol: str = ""
    kind: str = ""
    symbol_path: str = ""
    symbol_parent: str = ""
    symbol_signature: str = ""
    symbol_docstring: str = ""
    is_semantic: bool = True
    concept: str = ""
    calls: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)


class SearchOptimizedChunker:
    """
    Search-Optimized Semantic Chunker - designed for code search engines.
    
    Algorithm:
    1. Extract semantic units using language mappings
    2. Classify each unit by concept type
    3. Deduplicate identical content
    4. Split oversized units (concept-aware)
    5. Merge compatible adjacent units
    6. Prevent nested chunk merging
    7. Emergency split minified code
    """
    
    def __init__(self, config: Optional[SOSCConfig] = None):
        self.config = config or SOSCConfig()
        self._seen_hashes: Set[str] = set()
    
    def chunk(self, content: str, language: str) -> List[ChunkResult]:
        """
        Chunk code using search-optimized algorithm.
        
        Args:
            content: Source code content
            language: Programming language
            
        Returns:
            List of ChunkResult objects ready for pipeline
        """
        if not content.strip():
            return []
        
        self._seen_hashes.clear()
        
        chunks = self._extract_semantic_units(content, language)
        if not chunks:
            return [self._content_to_result(content, 1, len(content.splitlines()))]
        
        if self.config.deduplicate:
            chunks = self._deduplicate(chunks)
        
        chunks = self._split_oversized(chunks, content)
        chunks = self._merge_compatible(chunks, content)
        chunks = [c for c in chunks if c.non_whitespace_chars >= self.config.min_chunk_chars]
        
        return [self._chunk_to_result(c) for c in chunks]
    
    def _extract_semantic_units(self, content: str, language: str) -> List[SemanticChunk]:
        try:
            from scripts.ingest.concept_extractor import extract_concepts
            concepts = extract_concepts(content, language)
            if concepts:
                return [
                    SemanticChunk(
                        concept=self._map_concept_type(c.concept),
                        name=c.name,
                        content=c.content,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        kind=c.kind,
                        parent=c.metadata.get("parent"),
                        signature=c.metadata.get("signature"),
                        docstring=c.metadata.get("docstring"),
                    )
                    for c in concepts
                ]
        except ImportError:
            pass
        
        return self._fallback_extract_symbols(content, language)
    
    def _map_concept_type(self, lm_concept):
        from scripts.ingest.language_mappings import ConceptType as LMConceptType
        mapping = {
            LMConceptType.DEFINITION: ConceptType.DEFINITION,
            LMConceptType.BLOCK: ConceptType.BLOCK,
            LMConceptType.COMMENT: ConceptType.COMMENT,
            LMConceptType.IMPORT: ConceptType.IMPORT,
            LMConceptType.STRUCTURE: ConceptType.STRUCTURE,
        }
        return mapping.get(lm_concept, ConceptType.BLOCK)
    
    def _fallback_extract_symbols(self, content: str, language: str) -> List[SemanticChunk]:
        from scripts.ingest.symbols import _extract_symbols
        
        lines = content.splitlines()
        symbols = _extract_symbols(language, content)
        
        if not symbols:
            return []
        
        chunks: List[SemanticChunk] = []
        symbols.sort(key=lambda s: s.start or 0)
        
        prev_end = 0
        
        for sym in symbols:
            sym_start = sym.start or 1
            sym_end = sym.end or sym_start
            
            if sym_start > prev_end + 1:
                gap_start = prev_end + 1 if prev_end > 0 else 1
                gap_end = sym_start - 1
                gap_text = "\n".join(lines[gap_start - 1:gap_end])
                if gap_text.strip():
                    concept = self._classify_concept(gap_text, None)
                    chunks.append(SemanticChunk(
                        concept=concept,
                        name="<module>",
                        content=gap_text,
                        start_line=gap_start,
                        end_line=gap_end,
                        kind="module_code",
                    ))
            
            sym_text = "\n".join(lines[sym_start - 1:sym_end])
            kind = getattr(sym, 'kind', None) or 'unknown'
            concept = self._classify_concept(sym_text, kind)
            
            chunks.append(SemanticChunk(
                concept=concept,
                name=sym.name or "",
                content=sym_text,
                start_line=sym_start,
                end_line=sym_end,
                kind=kind,
                parent=getattr(sym, 'parent', None),
                signature=getattr(sym, 'signature', None),
                docstring=getattr(sym, 'docstring', None),
            ))
            
            prev_end = sym_end
        
        if prev_end < len(lines):
            gap_text = "\n".join(lines[prev_end:])
            if gap_text.strip():
                concept = self._classify_concept(gap_text, None)
                chunks.append(SemanticChunk(
                    concept=concept,
                    name="<module>",
                    content=gap_text,
                    start_line=prev_end + 1,
                    end_line=len(lines),
                    kind="module_code",
                ))
        
        return chunks
    
    def _classify_concept(self, text: str, kind: Optional[str]) -> ConceptType:
        """Classify content into a concept type."""
        if kind in ('function', 'method', 'class', 'type', 'const', 'variable'):
            return ConceptType.DEFINITION
        if kind in ('block', 'if', 'for', 'while', 'try', 'with'):
            return ConceptType.BLOCK
        if kind in ('comment', 'docstring'):
            return ConceptType.COMMENT
        if kind in ('import', 'include', 'require', 'use'):
            return ConceptType.IMPORT
        
        # Heuristic classification from content
        stripped = text.strip()
        if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
            return ConceptType.COMMENT
        if any(kw in stripped[:50] for kw in ['import ', 'from ', 'require(', 'include ', '#include']):
            return ConceptType.IMPORT
        if any(kw in stripped[:50] for kw in ['def ', 'function ', 'class ', 'fn ', 'func ']):
            return ConceptType.DEFINITION
        
        return ConceptType.BLOCK  # Default
    
    def _deduplicate(self, chunks: List[SemanticChunk]) -> List[SemanticChunk]:
        """Remove chunks with identical content."""
        result = []
        for chunk in chunks:
            if chunk.content_hash not in self._seen_hashes:
                self._seen_hashes.add(chunk.content_hash)
                result.append(chunk)
        return result
    
    def _split_oversized(self, chunks: List[SemanticChunk], content: str) -> List[SemanticChunk]:
        """Split chunks that exceed size limits."""
        result = []
        for chunk in chunks:
            if self._needs_split(chunk):
                result.extend(self._split_chunk(chunk, content))
            else:
                result.append(chunk)
        return result
    
    def _needs_split(self, chunk: SemanticChunk) -> bool:
        """Check if chunk exceeds size limits."""
        return (chunk.non_whitespace_chars > self.config.max_chunk_chars or
                chunk.estimated_tokens > self.config.safe_token_limit)
    
    def _split_chunk(self, chunk: SemanticChunk, content: str) -> List[SemanticChunk]:
        """Split an oversized chunk intelligently."""
        lines = chunk.content.split('\n')
        
        # Analyze: is this minified code?
        if self._is_minified(lines):
            return self._emergency_split(chunk)
        
        # Regular code: split at line boundaries
        return self._line_split(chunk, lines)
    
    def _is_minified(self, lines: List[str]) -> bool:
        """Detect minified/concatenated code."""
        if len(lines) <= 2:
            return True
        max_len = max(len(line) for line in lines) if lines else 0
        # If any line is >20% of max chunk size, it's likely minified
        return max_len > self.config.max_chunk_chars * 0.2
    
    def _emergency_split(self, chunk: SemanticChunk) -> List[SemanticChunk]:
        """Split minified code at syntax boundaries."""
        result = []
        remaining = chunk.content
        part = 1
        max_chars = int(self.config.max_chunk_chars * 0.8)  # Safety margin
        
        while remaining:
            if len(re.sub(r'\s', '', remaining)) <= self.config.max_chunk_chars:
                result.append(self._create_split_chunk(chunk, remaining, part, len(result)))
                break
            
            # Find best split point
            best_split = 0
            for char in self.config.split_chars:
                pos = remaining.rfind(char, 0, max_chars)
                if pos > best_split:
                    best_split = pos + 1
                    break
            
            if best_split == 0:
                best_split = max_chars  # Force split
            
            result.append(self._create_split_chunk(chunk, remaining[:best_split], part, len(result)))
            remaining = remaining[best_split:]
            part += 1
        
        return result
    
    def _line_split(self, chunk: SemanticChunk, lines: List[str]) -> List[SemanticChunk]:
        """Split at line boundaries (binary split)."""
        if len(lines) <= 2:
            return [chunk]
        
        mid = len(lines) // 2
        
        chunk1 = SemanticChunk(
            concept=chunk.concept,
            name=f"{chunk.name}_part1",
            content="\n".join(lines[:mid]),
            start_line=chunk.start_line,
            end_line=chunk.start_line + mid - 1,
            kind=chunk.kind,
            parent=chunk.parent,
        )
        
        chunk2 = SemanticChunk(
            concept=chunk.concept,
            name=f"{chunk.name}_part2",
            content="\n".join(lines[mid:]),
            start_line=chunk.start_line + mid,
            end_line=chunk.end_line,
            kind=chunk.kind,
            parent=chunk.parent,
        )
        
        # Recursive split if still too large
        result = []
        for c in [chunk1, chunk2]:
            if self._needs_split(c):
                result.extend(self._split_chunk(c, c.content))
            else:
                result.append(c)
        
        return result
    
    def _create_split_chunk(self, original: SemanticChunk, content: str, 
                           part: int, total_parts: int) -> SemanticChunk:
        """Create a split chunk with adjusted line numbers."""
        # Approximate line distribution
        lines_per_part = (original.end_line - original.start_line + 1) // max(total_parts + 1, 1)
        start = original.start_line + (part - 1) * lines_per_part
        end = min(start + lines_per_part - 1, original.end_line)
        
        return SemanticChunk(
            concept=original.concept,
            name=f"{original.name}_part{part}",
            content=content,
            start_line=start,
            end_line=end,
            kind=original.kind,
            parent=original.parent,
        )
    
    def _merge_compatible(self, chunks: List[SemanticChunk], content: str) -> List[SemanticChunk]:
        """Merge adjacent compatible chunks."""
        if len(chunks) <= 1:
            return chunks
        
        # Sort by line position
        sorted_chunks = sorted(chunks, key=lambda c: c.start_line)
        result = []
        current = sorted_chunks[0]
        
        for next_chunk in sorted_chunks[1:]:
            if self._can_merge(current, next_chunk):
                current = self._merge_chunks(current, next_chunk)
            else:
                result.append(current)
                current = next_chunk
        
        result.append(current)
        return result
    
    def _can_merge(self, c1: SemanticChunk, c2: SemanticChunk) -> bool:
        """Check if two chunks can be merged."""
        # Size check
        combined_chars = c1.non_whitespace_chars + c2.non_whitespace_chars
        if combined_chars > self.config.max_chunk_chars * self.config.merge_threshold:
            return False
        
        # Token check
        combined_tokens = c1.estimated_tokens + c2.estimated_tokens
        if combined_tokens > self.config.safe_token_limit * self.config.merge_threshold:
            return False
        
        # Gap check
        gap = c2.start_line - c1.end_line - 1
        max_gap = (self.config.comment_merge_gap 
                   if c1.concept == ConceptType.COMMENT or c2.concept == ConceptType.COMMENT
                   else self.config.max_merge_gap_lines)
        if gap > max_gap:
            return False
        
        # Concept compatibility
        if c1.concept != c2.concept:
            if (c1.concept, c2.concept) not in COMPATIBLE_MERGE_PAIRS:
                return False
        
        # Nested prevention
        if self.config.prevent_nested_merge:
            # Don't merge if c2 is nested inside c1's range
            if c2.start_line > c1.start_line and c2.end_line <= c1.end_line:
                return False
        
        # Same parent preference
        if c1.parent and c2.parent and c1.parent == c2.parent:
            return True
        
        return True
    
    def _merge_chunks(self, c1: SemanticChunk, c2: SemanticChunk) -> SemanticChunk:
        """Merge two chunks into one."""
        # Prefer DEFINITION over COMMENT when merging
        if c1.concept == ConceptType.DEFINITION:
            concept, name, kind = c1.concept, c1.name, c1.kind
        elif c2.concept == ConceptType.DEFINITION:
            concept, name, kind = c2.concept, c2.name, c2.kind
        else:
            concept, name, kind = c1.concept, c1.name, c1.kind
        
        return SemanticChunk(
            concept=concept,
            name=name,
            content=c1.content + "\n" + c2.content,
            start_line=c1.start_line,
            end_line=c2.end_line,
            kind=kind,
            parent=c1.parent or c2.parent,
            signature=c1.signature or c2.signature,
            docstring=c1.docstring or c2.docstring,
        )
    
    def _chunk_to_result(self, chunk: SemanticChunk) -> ChunkResult:
        """Convert internal chunk to pipeline format."""
        return ChunkResult(
            text=chunk.content,
            start=chunk.start_line,
            end=chunk.end_line,
            symbol=chunk.name if chunk.name != "<module>" else "",
            kind=chunk.kind,
            symbol_parent=chunk.parent or "",
            symbol_signature=chunk.signature or "",
            symbol_docstring=chunk.docstring or "",
            is_semantic=True,
            concept=chunk.concept.value,
        )
    
    def _content_to_result(self, content: str, start: int, end: int) -> ChunkResult:
        """Convert raw content to result (fallback)."""
        return ChunkResult(
            text=content,
            start=start,
            end=end,
            is_semantic=False,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_DEFAULT_CHUNKER: Optional[SearchOptimizedChunker] = None


def get_search_chunker(config: Optional[SOSCConfig] = None) -> SearchOptimizedChunker:
    """Get or create the search-optimized chunker."""
    global _DEFAULT_CHUNKER
    
    if config is not None:
        return SearchOptimizedChunker(config)
    
    if _DEFAULT_CHUNKER is None:
        _DEFAULT_CHUNKER = SearchOptimizedChunker()
    
    return _DEFAULT_CHUNKER


def chunk_search_optimized(
    text: str,
    language: str,
    config: Optional[SOSCConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Chunk code using search-optimized algorithm.
    
    This is the main public function for the new chunking strategy.
    
    Args:
        text: Source code content
        language: Programming language
        config: Optional SOSCConfig for customization
        
    Returns:
        List of chunk dicts compatible with existing pipeline
    """
    chunker = get_search_chunker(config)
    results = chunker.chunk(text, language)
    
    return [
        {
            "text": r.text,
            "start": r.start,
            "end": r.end,
            "symbol": r.symbol,
            "kind": r.kind,
            "symbol_path": r.symbol_path,
            "symbol_parent": r.symbol_parent,
            "symbol_signature": r.symbol_signature,
            "symbol_docstring": r.symbol_docstring,
            "is_semantic": r.is_semantic,
            "concept": r.concept,
            "calls": r.calls,
            "imports": r.imports,
        }
        for r in results
    ]
