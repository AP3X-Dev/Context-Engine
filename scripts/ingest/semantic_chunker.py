#!/usr/bin/env python3
"""
ingest/semantic_chunker.py - Semantic Density Chunker (SDC).

A token-aware, AST-driven chunking algorithm that:
1. Respects semantic boundaries (functions, classes, methods)
2. Uses token budgets instead of line counts
3. Merges adjacent small units for optimal chunk density
4. Scores chunks by information density

This is Context-Engine's original chunking approach.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class SDCConfig:
    """Configuration for Semantic Density Chunker."""
    # Token budget (target range for chunk sizes)
    min_tokens: int = 200       # Minimum tokens per chunk
    target_tokens: int = 800    # Target tokens per chunk
    max_tokens: int = 1500      # Maximum tokens per chunk (hard limit)
    
    # Merge behavior
    merge_threshold: float = 0.7  # Merge if combined size <= target * threshold
    max_merge_gap_lines: int = 5  # Max blank lines between symbols to merge
    
    # Quality thresholds
    min_density: float = 0.3    # Minimum code density (vs comments/whitespace)
    
    # Context inclusion
    include_imports: bool = True      # Include relevant imports at chunk start
    include_class_context: bool = True  # Include class signature for methods
    
    # Token estimation (chars per token, approximation)
    chars_per_token: float = 4.0


@dataclass
class SemanticUnit:
    """Represents a semantic code unit (function, class, method, etc)."""
    kind: str                    # function, class, method, module_code
    name: str
    start_line: int
    end_line: int
    text: str
    token_count: int
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)
    complexity: int = 0
    density_score: float = 1.0
    path: Optional[str] = None   # Fully qualified path


@dataclass
class ChunkResult:
    """Result of chunking operation."""
    text: str
    start_line: int
    end_line: int
    symbols: List[str]
    symbol_kinds: List[str]
    token_count: int
    density_score: float
    is_merged: bool = False      # True if this chunk was created by merging units


class SemanticDensityChunker:
    """
    Semantic Density Chunker - token-aware AST-driven chunking.
    
    Algorithm:
    1. Parse code and extract semantic units (functions, classes, methods)
    2. Estimate token counts for each unit
    3. Score units by information density
    4. Merge adjacent small units when beneficial
    5. Split oversized units at logical boundaries
    6. Add contextual information (imports, class signatures)
    """
    
    def __init__(self, config: Optional[SDCConfig] = None):
        """Initialize chunker with configuration."""
        self.config = config or SDCConfig()
        self._tokenizer = None
        self._tokenizer_loaded = False
    
    def _load_tokenizer(self):
        """Lazy-load tokenizer for accurate token counting."""
        if self._tokenizer_loaded:
            return
        self._tokenizer_loaded = True
        
        try:
            from tokenizers import Tokenizer
            from scripts.ingest.config import ROOT_DIR
            tok_path = os.environ.get(
                "TOKENIZER_JSON", 
                str(ROOT_DIR / "models" / "tokenizer.json")
            )
            if os.path.exists(tok_path):
                self._tokenizer = Tokenizer.from_file(tok_path)
        except Exception:
            pass  # Will use estimation
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        self._load_tokenizer()
        
        if self._tokenizer:
            try:
                enc = self._tokenizer.encode(text)
                return len(enc.ids)
            except Exception:
                pass
        
        # Fallback: character-based estimation
        # Remove excess whitespace for better estimation
        compressed = re.sub(r'\s+', ' ', text)
        return max(1, int(len(compressed) / self.config.chars_per_token))
    
    def _calculate_density(self, text: str) -> float:
        """Calculate information density score (0-1).
        
        Higher = more actual code vs comments/whitespace.
        """
        if not text.strip():
            return 0.0
        
        lines = text.splitlines()
        total_chars = len(text)
        if total_chars == 0:
            return 0.0
        
        # Count different content types
        code_chars = 0
        comment_chars = 0
        
        in_multiline_comment = False
        for line in lines:
            stripped = line.strip()
            
            # Track multiline comments (Python docstrings, /* */ blocks)
            if '"""' in stripped or "'''" in stripped:
                in_multiline_comment = not in_multiline_comment
                comment_chars += len(line)
                continue
            
            if in_multiline_comment:
                comment_chars += len(line)
                continue
            
            # Single-line comments
            if stripped.startswith('#') or stripped.startswith('//'):
                comment_chars += len(line)
            else:
                code_chars += len(stripped)
        
        # Density = code / (code + comments), normalized
        meaningful = code_chars + comment_chars
        if meaningful == 0:
            return 0.0

        return min(1.0, code_chars / meaningful)

    def _extract_semantic_units(
        self, content: str, language: str
    ) -> List[SemanticUnit]:
        """Extract semantic units from code using AST analysis."""
        from scripts.ingest.symbols import _extract_symbols

        lines = content.splitlines()
        symbols = _extract_symbols(language, content)

        if not symbols:
            # No symbols found - treat entire content as one unit
            text = content
            return [SemanticUnit(
                kind="module_code",
                name="<module>",
                start_line=1,
                end_line=len(lines),
                text=text,
                token_count=self._estimate_tokens(text),
                density_score=self._calculate_density(text),
            )]

        units: List[SemanticUnit] = []
        symbols.sort(key=lambda s: s.start)

        # Track gaps between symbols (module-level code)
        prev_end = 0

        for sym in symbols:
            # Check for module-level code before this symbol
            if sym.start > prev_end + 1:
                gap_text = "\n".join(lines[prev_end:sym.start - 1])
                if gap_text.strip():
                    units.append(SemanticUnit(
                        kind="module_code",
                        name="<module>",
                        start_line=prev_end + 1,
                        end_line=sym.start - 1,
                        text=gap_text,
                        token_count=self._estimate_tokens(gap_text),
                        density_score=self._calculate_density(gap_text),
                    ))

            # Extract symbol text
            sym_text = "\n".join(lines[sym.start - 1:sym.end])

            units.append(SemanticUnit(
                kind=sym.kind or "unknown",
                name=sym.name or "",
                start_line=sym.start,
                end_line=sym.end,
                text=sym_text,
                token_count=self._estimate_tokens(sym_text),
                parent=getattr(sym, 'parent', None),
                path=getattr(sym, 'path', None),
                density_score=self._calculate_density(sym_text),
            ))

            prev_end = sym.end

        # Check for trailing module-level code
        if prev_end < len(lines):
            gap_text = "\n".join(lines[prev_end:])
            if gap_text.strip():
                units.append(SemanticUnit(
                    kind="module_code",
                    name="<module>",
                    start_line=prev_end + 1,
                    end_line=len(lines),
                    text=gap_text,
                    token_count=self._estimate_tokens(gap_text),
                    density_score=self._calculate_density(gap_text),
                ))

        return units

    def _should_merge(self, unit1: SemanticUnit, unit2: SemanticUnit) -> bool:
        """Determine if two adjacent units should be merged."""
        combined_tokens = unit1.token_count + unit2.token_count

        # Don't merge if combined would exceed target
        if combined_tokens > self.config.target_tokens * self.config.merge_threshold:
            return False

        # Check gap between units
        gap = unit2.start_line - unit1.end_line - 1
        if gap > self.config.max_merge_gap_lines:
            return False

        # Prefer merging units with same parent (methods of same class)
        if unit1.parent and unit1.parent == unit2.parent:
            return True

        # Prefer merging small related units
        if unit1.token_count < self.config.min_tokens or unit2.token_count < self.config.min_tokens:
            return True

        # Don't merge unrelated large units
        return combined_tokens <= self.config.min_tokens * 2

    def _merge_pass(self, units: List[SemanticUnit]) -> List[SemanticUnit]:
        """Merge adjacent small units when beneficial."""
        if not units:
            return units

        merged: List[SemanticUnit] = []
        i = 0

        while i < len(units):
            current = units[i]

            # Try to merge with subsequent units
            while i + 1 < len(units):
                next_unit = units[i + 1]

                if not self._should_merge(current, next_unit):
                    break

                # Merge the units
                combined_text = current.text + "\n" + next_unit.text
                current = SemanticUnit(
                    kind="merged",
                    name=f"{current.name}+{next_unit.name}",
                    start_line=current.start_line,
                    end_line=next_unit.end_line,
                    text=combined_text,
                    token_count=self._estimate_tokens(combined_text),
                    density_score=self._calculate_density(combined_text),
                    parent=current.parent if current.parent == next_unit.parent else None,
                )
                i += 1

            merged.append(current)
            i += 1

        return merged

    def _split_oversized_unit(
        self, unit: SemanticUnit, lines: List[str]
    ) -> List[SemanticUnit]:
        """Split an oversized unit at logical boundaries."""
        if unit.token_count <= self.config.max_tokens:
            return [unit]

        # Split based on token budget
        unit_lines = lines[unit.start_line - 1:unit.end_line]
        result: List[SemanticUnit] = []

        current_lines: List[str] = []
        current_start = unit.start_line
        current_tokens = 0

        for i, line in enumerate(unit_lines):
            line_tokens = self._estimate_tokens(line)

            # Check if adding this line would exceed budget
            if current_tokens + line_tokens > self.config.target_tokens and current_lines:
                # Create chunk from accumulated lines
                chunk_text = "\n".join(current_lines)
                result.append(SemanticUnit(
                    kind=unit.kind,
                    name=f"{unit.name}_part{len(result)+1}",
                    start_line=current_start,
                    end_line=current_start + len(current_lines) - 1,
                    text=chunk_text,
                    token_count=self._estimate_tokens(chunk_text),
                    parent=unit.parent,
                    path=unit.path,
                    density_score=self._calculate_density(chunk_text),
                ))
                current_lines = []
                current_start = unit.start_line + i
                current_tokens = 0

            current_lines.append(line)
            current_tokens += line_tokens

        # Don't forget the last chunk
        if current_lines:
            chunk_text = "\n".join(current_lines)
            result.append(SemanticUnit(
                kind=unit.kind,
                name=f"{unit.name}_part{len(result)+1}" if result else unit.name,
                start_line=current_start,
                end_line=unit.end_line,
                text=chunk_text,
                token_count=self._estimate_tokens(chunk_text),
                parent=unit.parent,
                path=unit.path,
                density_score=self._calculate_density(chunk_text),
            ))

        return result if result else [unit]

    def chunk(
        self, content: str, language: str
    ) -> List[ChunkResult]:
        """
        Chunk code using semantic density algorithm.

        Args:
            content: Source code content
            language: Programming language

        Returns:
            List of ChunkResult objects
        """
        lines = content.splitlines()

        # Step 1: Extract semantic units
        units = self._extract_semantic_units(content, language)

        # Step 2: Split oversized units
        split_units: List[SemanticUnit] = []
        for unit in units:
            split_units.extend(self._split_oversized_unit(unit, lines))

        # Step 3: Merge small adjacent units
        merged_units = self._merge_pass(split_units)

        # Step 4: Convert to ChunkResult format
        results: List[ChunkResult] = []
        for unit in merged_units:
            # Skip low-density chunks if they're very small
            if unit.density_score < self.config.min_density and unit.token_count < self.config.min_tokens:
                continue

            results.append(ChunkResult(
                text=unit.text,
                start_line=unit.start_line,
                end_line=unit.end_line,
                symbols=[unit.name] if unit.name and unit.name != "<module>" else [],
                symbol_kinds=[unit.kind] if unit.kind != "module_code" else [],
                token_count=unit.token_count,
                density_score=unit.density_score,
                is_merged=unit.kind == "merged",
            ))

        return results

    def chunk_to_dicts(
        self, content: str, language: str
    ) -> List[Dict[str, Any]]:
        """
        Chunk code and return as list of dicts (compatible with existing pipeline).

        This is the main entry point for integration with the ingestion pipeline.
        """
        results = self.chunk(content, language)

        return [
            {
                "text": r.text,
                "start": r.start_line,
                "end": r.end_line,
                "symbol": r.symbols[0] if r.symbols else "",
                "kind": r.symbol_kinds[0] if r.symbol_kinds else "",
                "token_count": r.token_count,
                "density_score": r.density_score,
                "is_semantic": not r.is_merged,
            }
            for r in results
        ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_DEFAULT_CHUNKER: Optional[SemanticDensityChunker] = None


def get_semantic_chunker(config: Optional[SDCConfig] = None) -> SemanticDensityChunker:
    """Get or create the default semantic chunker."""
    global _DEFAULT_CHUNKER

    if config is not None:
        return SemanticDensityChunker(config)

    if _DEFAULT_CHUNKER is None:
        _DEFAULT_CHUNKER = SemanticDensityChunker()

    return _DEFAULT_CHUNKER


def chunk_semantic_density(
    text: str,
    language: str,
    config: Optional[SDCConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Chunk code using semantic density algorithm.

    This is the main public function for the new chunking strategy.

    Args:
        text: Source code content
        language: Programming language
        config: Optional SDCConfig for customization

    Returns:
        List of chunk dicts compatible with existing pipeline
    """
    chunker = get_semantic_chunker(config)
    return chunker.chunk_to_dicts(text, language)

