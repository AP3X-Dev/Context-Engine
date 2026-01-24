#!/usr/bin/env python3
"""
ingest/cast_chunker.py - CAST+ Hybrid Chunker.

Combines cAST's concept-aware merging with SDC's density scoring:
- Concept-aware grouping (DEFINITION, BLOCK, COMMENT, IMPORT, STRUCTURE)
- Compatible concept pair merging (docstring+function OK, block+definition NO)
- Density scoring for quality assessment
- Emergency splitting for minified code
- Deduplication of identical content
- Nested chunk prevention

This is Context-Engine's enhanced chunking approach.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class CASTPlusConfig:
    """Configuration for CAST+ Hybrid Chunker."""
    # Size limits (non-whitespace characters)
    max_chunk_size: int = 1200       # Max non-whitespace chars per chunk
    min_chunk_size: int = 50         # Min size to avoid tiny fragments
    
    # Token limits
    safe_token_limit: int = 6000     # Conservative token limit
    chars_per_token: float = 3.5     # Conservative estimation ratio
    
    # Merge behavior
    merge_threshold: float = 0.8     # Merge if combined < threshold * max
    max_line_gap_same_concept: int = 5   # Max gap for same concept
    max_line_gap_cross_concept: int = 1  # Max gap for compatible concepts
    
    # Quality thresholds
    min_density: float = 0.3         # Minimum code density
    
    # Features
    greedy_merge: bool = True        # Final greedy merge pass
    deduplicate: bool = True         # Remove duplicate content


class ConceptType(Enum):
    """Universal semantic concepts (mirrors language_mappings.base)."""
    DEFINITION = "definition"
    BLOCK = "block"
    COMMENT = "comment"
    IMPORT = "import"
    STRUCTURE = "structure"


# Compatible concept pairs that can be merged
COMPATIBLE_PAIRS: Set[Tuple[ConceptType, ConceptType]] = {
    (ConceptType.COMMENT, ConceptType.DEFINITION),
    (ConceptType.DEFINITION, ConceptType.COMMENT),
    (ConceptType.BLOCK, ConceptType.COMMENT),
    (ConceptType.COMMENT, ConceptType.BLOCK),
    (ConceptType.DEFINITION, ConceptType.STRUCTURE),
    (ConceptType.STRUCTURE, ConceptType.DEFINITION),
}


@dataclass
class SemanticChunk:
    """A semantic code chunk with concept awareness (search-optimized)."""
    concept: ConceptType
    name: str
    content: str
    start_line: int
    end_line: int
    kind: str = ""                   # function, class, method, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Parent tracking (for metadata, NOT embedded in content)
    parent: Optional[str] = None     # Parent class/module name

    # Computed metrics
    non_whitespace_chars: int = 0
    estimated_tokens: int = 0
    density_score: float = 1.0

    def __post_init__(self):
        """Compute metrics after initialization."""
        if self.non_whitespace_chars == 0:
            self.non_whitespace_chars = len(re.sub(r"\s", "", self.content))
        if self.estimated_tokens == 0:
            self.estimated_tokens = int(self.non_whitespace_chars / 3.5)
        if self.density_score == 1.0:
            self.density_score = self._calculate_density()

    def _calculate_density(self) -> float:
        """Calculate code density (code vs whitespace/comments)."""
        if not self.content:
            return 0.0
        total = len(self.content)
        if total == 0:
            return 0.0
        return self.non_whitespace_chars / total


@dataclass
class ChunkResult:
    """Result of chunking operation (search-optimized)."""
    text: str
    start_line: int
    end_line: int
    symbols: List[str]
    symbol_kinds: List[str]
    concept: str
    token_count: int
    density_score: float
    parent: Optional[str] = None     # Parent for metadata
    is_merged: bool = False
    merged_from: List[str] = field(default_factory=list)


class CASTPlusChunker:
    """
    CAST+ Hybrid Chunker - concept-aware semantic chunking.
    
    Algorithm:
    1. Extract semantic concepts using language mappings
    2. Deduplicate identical content
    3. Group by concept type
    4. Apply concept-specific chunking strategies:
       - DEFINITION: Keep intact, split only if oversized
       - BLOCK: Merge aggressively with compatible chunks
       - COMMENT: Merge consecutive comments
    5. Greedy merge pass for final optimization
    6. Score chunks by information density
    """
    
    def __init__(self, config: Optional[CASTPlusConfig] = None):
        """Initialize chunker with configuration."""
        self.config = config or CASTPlusConfig()
        self._tokenizer = None
        self._tokenizer_loaded = False
    
    def _load_tokenizer(self):
        """Lazy-load tokenizer for accurate token counting."""
        if self._tokenizer_loaded:
            return
        self._tokenizer_loaded = True
        try:
            import tiktoken
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self._tokenizer = None
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        self._load_tokenizer()
        if self._tokenizer:
            try:
                return len(self._tokenizer.encode(text))
            except Exception:
                pass
        # Fallback: conservative char-based estimation
        non_ws = len(re.sub(r"\s", "", text))
        return int(non_ws / self.config.chars_per_token)
    
    def _calculate_density(self, text: str) -> float:
        """Calculate code density score."""
        if not text:
            return 0.0
        total = len(text)
        non_ws = len(re.sub(r"\s", "", text))
        return non_ws / total if total > 0 else 0.0

    def _non_whitespace_chars(self, text: str) -> int:
        """Count non-whitespace characters."""
        return len(re.sub(r"\s", "", text))

    # -------------------------------------------------------------------------
    # Deduplication
    # -------------------------------------------------------------------------
    def _deduplicate_chunks(self, chunks: List[SemanticChunk]) -> List[SemanticChunk]:
        """Remove chunks with identical content, keeping most specific."""
        if not self.config.deduplicate or not chunks:
            return chunks

        seen_content: Dict[str, SemanticChunk] = {}
        for chunk in chunks:
            key = chunk.content.strip()
            if key in seen_content:
                # Keep the more specific one (DEFINITION > BLOCK > COMMENT)
                existing = seen_content[key]
                priority = {ConceptType.DEFINITION: 3, ConceptType.BLOCK: 2,
                           ConceptType.COMMENT: 1, ConceptType.IMPORT: 2,
                           ConceptType.STRUCTURE: 0}
                if priority.get(chunk.concept, 0) > priority.get(existing.concept, 0):
                    seen_content[key] = chunk
            else:
                seen_content[key] = chunk

        return list(seen_content.values())

    # -------------------------------------------------------------------------
    # Merge Logic
    # -------------------------------------------------------------------------
    def _can_merge(
        self,
        current: SemanticChunk,
        candidate: SemanticChunk
    ) -> bool:
        """Check if two chunks can be merged."""
        # cAST: Check prevent_merge_across_concepts metadata
        if current.metadata.get("prevent_merge_across_concepts", False):
            return False
        if candidate.metadata.get("prevent_merge_across_concepts", False):
            return False

        # Calculate combined size
        combined = current.content + "\n" + candidate.content
        combined_chars = self._non_whitespace_chars(combined)
        combined_tokens = self._estimate_tokens(combined)

        # Check size constraints
        max_chars = self.config.max_chunk_size * self.config.merge_threshold
        max_tokens = self.config.safe_token_limit * self.config.merge_threshold

        if combined_chars > max_chars or combined_tokens > max_tokens:
            return False

        # Check line proximity
        line_gap = candidate.start_line - current.end_line

        if current.concept == candidate.concept:
            if line_gap > self.config.max_line_gap_same_concept:
                return False
        else:
            # Cross-concept merge - check compatibility
            if (current.concept, candidate.concept) not in COMPATIBLE_PAIRS:
                return False
            if line_gap > self.config.max_line_gap_cross_concept:
                return False

        # Prevent merging nested chunks (cAST)
        if (candidate.start_line > current.start_line and
            candidate.end_line <= current.end_line):
            return False

        return True

    def _should_prefer_merge(
        self,
        current: SemanticChunk,
        candidate: SemanticChunk
    ) -> bool:
        """SDC: Check if merge is preferred (same parent = prefer merge)."""
        # Prefer merging chunks with same parent (methods of same class)
        if current.parent and current.parent == candidate.parent:
            return True
        return False

    def _merge_chunks(
        self,
        chunks: List[SemanticChunk]
    ) -> SemanticChunk:
        """Merge multiple chunks into one."""
        if len(chunks) == 1:
            return chunks[0]

        sorted_chunks = sorted(chunks, key=lambda c: c.start_line)

        # Combine content without duplication
        combined_content = sorted_chunks[0].content
        for chunk in sorted_chunks[1:]:
            if chunk.content.strip() not in combined_content:
                combined_content += "\n" + chunk.content

        # Combine names
        names = [c.name for c in sorted_chunks if c.name]
        merged_name = "_".join(dict.fromkeys(names)) if names else "merged"

        # Combine kinds
        kinds = [c.kind for c in sorted_chunks if c.kind]
        merged_kind = kinds[0] if kinds else ""

        return SemanticChunk(
            concept=sorted_chunks[0].concept,
            name=merged_name,
            content=combined_content,
            start_line=sorted_chunks[0].start_line,
            end_line=sorted_chunks[-1].end_line,
            kind=merged_kind,
            metadata={
                "merged_from": [c.name for c in sorted_chunks],
                "chunk_count": len(sorted_chunks),
            },
        )

    # -------------------------------------------------------------------------
    # Splitting Logic
    # -------------------------------------------------------------------------
    def _needs_split(self, chunk: SemanticChunk) -> bool:
        """Check if chunk exceeds size limits."""
        return (chunk.non_whitespace_chars > self.config.max_chunk_size or
                chunk.estimated_tokens > self.config.safe_token_limit)

    def _split_chunk(self, chunk: SemanticChunk) -> List[SemanticChunk]:
        """Split an oversized chunk at logical boundaries."""
        if not self._needs_split(chunk):
            return [chunk]

        lines = chunk.content.split("\n")

        # Analyze content structure
        max_line_len = max(len(line) for line in lines) if lines else 0

        # If very long lines (minified code), use emergency split
        if len(lines) <= 2 or max_line_len > self.config.max_chunk_size * 0.2:
            return self._emergency_split(chunk)

        # Otherwise, use line-based binary split
        return self._binary_split(chunk, lines)

    def _binary_split(
        self,
        chunk: SemanticChunk,
        lines: List[str]
    ) -> List[SemanticChunk]:
        """Split chunk by lines using binary division."""
        if len(lines) <= 2:
            return [chunk]

        mid = len(lines) // 2

        content1 = "\n".join(lines[:mid])
        content2 = "\n".join(lines[mid:])

        chunk1 = SemanticChunk(
            concept=chunk.concept,
            name=f"{chunk.name}_part1",
            content=content1,
            start_line=chunk.start_line,
            end_line=chunk.start_line + mid - 1,
            kind=chunk.kind,
            metadata=chunk.metadata.copy(),
        )

        chunk2 = SemanticChunk(
            concept=chunk.concept,
            name=f"{chunk.name}_part2",
            content=content2,
            start_line=chunk.start_line + mid,
            end_line=chunk.end_line,
            kind=chunk.kind,
            metadata=chunk.metadata.copy(),
        )

        # Recursively split if still too large
        result = []
        for sub in [chunk1, chunk2]:
            if self._needs_split(sub):
                result.extend(self._split_chunk(sub))
            else:
                result.append(sub)

        return result

    def _emergency_split(self, chunk: SemanticChunk) -> List[SemanticChunk]:
        """Emergency split for minified/long-line code."""
        # Smart split points for code
        split_chars = [";", "}", "{", ",", " "]
        max_chars = self.config.max_chunk_size

        result = []
        remaining = chunk.content
        part_num = 1
        total_len = len(chunk.content)
        current_pos = 0

        while remaining:
            remaining_chars = self._non_whitespace_chars(remaining)
            if remaining_chars <= max_chars:
                result.append(self._create_split_chunk(
                    chunk, remaining, part_num, current_pos, total_len
                ))
                break

            # Find best split point
            best_split = 0
            for split_char in split_chars:
                pos = remaining.rfind(split_char, 0, max_chars)
                if pos > best_split:
                    test_content = remaining[:pos + 1]
                    if self._non_whitespace_chars(test_content) <= max_chars:
                        best_split = pos + 1
                        break

            # Force split if no good point found
            if best_split == 0:
                best_split = max_chars

            result.append(self._create_split_chunk(
                chunk, remaining[:best_split], part_num, current_pos, total_len
            ))
            remaining = remaining[best_split:]
            current_pos += best_split
            part_num += 1

        return result

    def _create_split_chunk(
        self,
        original: SemanticChunk,
        content: str,
        part_num: int,
        content_start: int,
        total_len: int,
    ) -> SemanticChunk:
        """Create a chunk from emergency splitting."""
        line_span = original.end_line - original.start_line + 1

        if total_len > 0:
            pos_ratio = content_start / total_len
            len_ratio = len(content) / total_len
            start_line = original.start_line + int(pos_ratio * line_span)
            end_line = start_line + max(1, int(len_ratio * line_span)) - 1
            end_line = min(end_line, original.end_line)
        else:
            start_line = original.start_line
            end_line = original.end_line

        return SemanticChunk(
            concept=original.concept,
            name=f"{original.name}_part{part_num}",
            content=content,
            start_line=start_line,
            end_line=end_line,
            kind=original.kind,
            metadata=original.metadata.copy(),
        )

    # -------------------------------------------------------------------------
    # Concept-Specific Chunking Strategies
    # -------------------------------------------------------------------------
    def _chunk_definitions(
        self,
        chunks: List[SemanticChunk]
    ) -> List[SemanticChunk]:
        """Chunk DEFINITION concepts - keep intact, split only if oversized."""
        result = []
        for chunk in chunks:
            result.extend(self._split_chunk(chunk))
        return result

    def _chunk_blocks(
        self,
        chunks: List[SemanticChunk]
    ) -> List[SemanticChunk]:
        """Chunk BLOCK concepts - merge aggressively."""
        if not chunks:
            return []

        sorted_chunks = sorted(chunks, key=lambda c: c.start_line)
        result = []
        current_group = [sorted_chunks[0]]

        for chunk in sorted_chunks[1:]:
            if self._can_merge(current_group[-1], chunk):
                current_group.append(chunk)
            else:
                merged = self._merge_chunks(current_group)
                result.extend(self._split_chunk(merged))
                current_group = [chunk]

        # Don't forget last group
        if current_group:
            merged = self._merge_chunks(current_group)
            result.extend(self._split_chunk(merged))

        return result

    def _chunk_comments(
        self,
        chunks: List[SemanticChunk]
    ) -> List[SemanticChunk]:
        """Chunk COMMENT concepts - merge consecutive only."""
        if not chunks:
            return []

        sorted_chunks = sorted(chunks, key=lambda c: c.start_line)
        result = []
        current_group = [sorted_chunks[0]]

        for chunk in sorted_chunks[1:]:
            last = current_group[-1]
            line_gap = chunk.start_line - last.end_line

            # Only merge consecutive comments (gap <= 1)
            if line_gap <= 1:
                current_group.append(chunk)
            else:
                merged = self._merge_chunks(current_group)
                result.extend(self._split_chunk(merged))
                current_group = [chunk]

        if current_group:
            merged = self._merge_chunks(current_group)
            result.extend(self._split_chunk(merged))

        return result

    def _greedy_merge_pass(
        self,
        chunks: List[SemanticChunk]
    ) -> List[SemanticChunk]:
        """Final greedy merge pass for maximum density."""
        if len(chunks) <= 1 or not self.config.greedy_merge:
            return chunks

        sorted_chunks = sorted(chunks, key=lambda c: c.start_line)
        result = []
        current = sorted_chunks[0]

        for next_chunk in sorted_chunks[1:]:
            # Check concept compatibility
            if current.concept != next_chunk.concept:
                if (current.concept, next_chunk.concept) not in COMPATIBLE_PAIRS:
                    result.append(current)
                    current = next_chunk
                    continue

            # Check if nested
            if (next_chunk.start_line > current.start_line and
                next_chunk.end_line <= current.end_line):
                result.append(current)
                current = next_chunk
                continue

            # Check if can merge
            if next_chunk.content.strip() not in current.content:
                combined = current.content + "\n" + next_chunk.content
            else:
                combined = current.content

            combined_chars = self._non_whitespace_chars(combined)
            combined_tokens = self._estimate_tokens(combined)

            if (combined_chars <= self.config.max_chunk_size and
                combined_tokens <= self.config.safe_token_limit):
                # Merge
                current = SemanticChunk(
                    concept=current.concept,
                    name=f"{current.name}_{next_chunk.name}",
                    content=combined,
                    start_line=current.start_line,
                    end_line=next_chunk.end_line,
                    kind=current.kind or next_chunk.kind,
                    metadata={"merged": True},
                )
            else:
                result.append(current)
                current = next_chunk

        result.append(current)
        return result

    # -------------------------------------------------------------------------
    # Main Chunking Entry Point
    # -------------------------------------------------------------------------
    def chunk(
        self,
        content: str,
        language: str,
        concepts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[ChunkResult]:
        """
        Chunk code using CAST+ algorithm.

        Args:
            content: Source code content
            language: Programming language
            concepts: Optional pre-extracted concepts from language mappings

        Returns:
            List of ChunkResult objects
        """
        # Step 1: Extract or convert concepts to SemanticChunks
        if concepts:
            chunks = self._concepts_to_chunks(concepts)
        else:
            chunks = self._extract_concepts(content, language)

        if not chunks:
            # Fallback: treat entire content as single chunk
            return [ChunkResult(
                text=content,
                start_line=1,
                end_line=len(content.splitlines()),
                symbols=[],
                symbol_kinds=[],
                concept="structure",
                token_count=self._estimate_tokens(content),
                density_score=self._calculate_density(content),
                parent=None,
            )]

        # Step 2: Deduplicate
        chunks = self._deduplicate_chunks(chunks)

        # Step 3: Group by concept type
        by_concept: Dict[ConceptType, List[SemanticChunk]] = {}
        for chunk in chunks:
            if chunk.concept not in by_concept:
                by_concept[chunk.concept] = []
            by_concept[chunk.concept].append(chunk)

        # Step 4: Apply concept-specific strategies
        optimized: List[SemanticChunk] = []

        for concept, concept_chunks in by_concept.items():
            if concept == ConceptType.DEFINITION:
                optimized.extend(self._chunk_definitions(concept_chunks))
            elif concept == ConceptType.BLOCK:
                optimized.extend(self._chunk_blocks(concept_chunks))
            elif concept == ConceptType.COMMENT:
                optimized.extend(self._chunk_comments(concept_chunks))
            else:
                # IMPORT, STRUCTURE - use block strategy
                optimized.extend(self._chunk_blocks(concept_chunks))

        # Step 5: Greedy merge pass
        optimized = self._greedy_merge_pass(optimized)

        # Step 6: Convert to ChunkResult
        results = []
        for chunk in optimized:
            # Skip low-density tiny chunks
            if (chunk.density_score < self.config.min_density and
                chunk.non_whitespace_chars < self.config.min_chunk_size):
                continue

            results.append(ChunkResult(
                text=chunk.content,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                symbols=[chunk.name] if chunk.name else [],
                symbol_kinds=[chunk.kind] if chunk.kind else [],
                concept=chunk.concept.value,
                token_count=chunk.estimated_tokens,
                density_score=chunk.density_score,
                parent=chunk.parent,
                is_merged=chunk.metadata.get("merged", False) or
                          chunk.metadata.get("chunk_count", 1) > 1,
                merged_from=chunk.metadata.get("merged_from", []),
            ))

        return results

    def _concepts_to_chunks(
        self,
        concepts: List[Dict[str, Any]]
    ) -> List[SemanticChunk]:
        """Convert concept dicts to SemanticChunk objects."""
        chunks = []
        for c in concepts:
            concept_str = c.get("concept", "structure")
            try:
                concept = ConceptType(concept_str)
            except ValueError:
                concept = ConceptType.STRUCTURE

            chunks.append(SemanticChunk(
                concept=concept,
                name=c.get("name", ""),
                content=c.get("content", ""),
                start_line=c.get("start_line", 1),
                end_line=c.get("end_line", 1),
                kind=c.get("kind", ""),
                metadata=c.get("metadata", {}),
            ))
        return chunks

    def _extract_concepts(
        self,
        content: str,
        language: str
    ) -> List[SemanticChunk]:
        """Extract concepts using language mappings via concept_extractor."""
        try:
            from scripts.ingest.concept_extractor import extract_concepts
            
            extracted = extract_concepts(content, language)
            if not extracted:
                return self._fallback_extract(content, language)
            
            chunks = []
            for ec in extracted:
                # Map concept_extractor.ConceptType to local ConceptType
                concept_str = ec.concept.value if hasattr(ec.concept, 'value') else str(ec.concept)
                try:
                    concept = ConceptType(concept_str)
                except ValueError:
                    concept = ConceptType.STRUCTURE
                
                chunks.append(SemanticChunk(
                    concept=concept,
                    name=ec.name,
                    content=ec.content,
                    start_line=ec.start_line,
                    end_line=ec.end_line,
                    kind=ec.kind,
                    metadata=ec.metadata,
                ))
            
            return chunks
            
        except ImportError:
            return self._fallback_extract(content, language)

    def _fallback_extract(
        self,
        content: str,
        language: str
    ) -> List[SemanticChunk]:
        """Fallback extraction using existing symbol extraction."""
        try:
            from scripts.ingest.symbols import extract_symbols

            symbols = extract_symbols(content, language)
            chunks = []
            lines = content.splitlines()

            for sym in symbols:
                start = sym.get("start", 1)
                end = sym.get("end", start)
                sym_content = "\n".join(lines[start - 1:end])

                # Map symbol kind to concept
                kind = sym.get("kind", "")
                if kind in ("function", "method", "class", "module"):
                    concept = ConceptType.DEFINITION
                elif kind in ("if", "for", "while", "try", "with"):
                    concept = ConceptType.BLOCK
                elif kind in ("comment", "docstring"):
                    concept = ConceptType.COMMENT
                elif kind in ("import", "include"):
                    concept = ConceptType.IMPORT
                else:
                    concept = ConceptType.STRUCTURE

                chunks.append(SemanticChunk(
                    concept=concept,
                    name=sym.get("name", ""),
                    content=sym_content,
                    start_line=start,
                    end_line=end,
                    kind=kind,
                ))

            return chunks

        except Exception:
            # Ultimate fallback: single chunk
            return [SemanticChunk(
                concept=ConceptType.STRUCTURE,
                name="file",
                content=content,
                start_line=1,
                end_line=len(content.splitlines()),
            )]

    def chunk_to_dicts(
        self,
        content: str,
        language: str,
        concepts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Chunk and return as list of dicts (pipeline compatible)."""
        results = self.chunk(content, language, concepts)

        return [
            {
                "text": r.text,
                "start": r.start_line,
                "end": r.end_line,
                "symbol": r.symbols[0] if r.symbols else "",
                "kind": r.symbol_kinds[0] if r.symbol_kinds else "",
                "concept": r.concept,
                "token_count": r.token_count,
                "density_score": r.density_score,
                "parent": r.parent,  # For metadata.symbol_parent
                "is_semantic": not r.is_merged,
            }
            for r in results
        ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_DEFAULT_CHUNKER: Optional[CASTPlusChunker] = None


def get_cast_chunker(config: Optional[CASTPlusConfig] = None) -> CASTPlusChunker:
    """Get or create the default CAST+ chunker."""
    global _DEFAULT_CHUNKER

    if config is not None:
        return CASTPlusChunker(config)

    if _DEFAULT_CHUNKER is None:
        _DEFAULT_CHUNKER = CASTPlusChunker()

    return _DEFAULT_CHUNKER


def chunk_cast_plus(
    text: str,
    language: str,
    concepts: Optional[List[Dict[str, Any]]] = None,
    config: Optional[CASTPlusConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Chunk code using CAST+ algorithm.

    This is the main public function for the hybrid chunking strategy.

    Args:
        text: Source code content
        language: Programming language
        concepts: Optional pre-extracted concepts
        config: Optional CASTPlusConfig for customization

    Returns:
        List of chunk dicts compatible with existing pipeline
    """
    chunker = get_cast_chunker(config)
    return chunker.chunk_to_dicts(text, language, concepts)

