# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""Pattern search MCP tool implementation.

Single unified tool that handles both code examples and natural language descriptions.
Supports TOON output format for token-efficient responses.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

# Import logger with fallback
try:
    from scripts.logger import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class QueryModeResult:
    """Result of query mode detection with confidence scoring."""
    mode: str  # "code" or "description"
    confidence: float  # 0.0 to 1.0
    signals: Dict[str, float]  # Individual signal contributions
    ast_validated: bool  # Whether AST parsing succeeded

# Import pattern detection components (lazy to avoid startup penalty)
_PATTERN_SEARCH_LOADED = False
_pattern_search_fn = None
_search_by_pattern_description_fn = None


def _ensure_pattern_search():
    """Lazy load pattern search module."""
    global _PATTERN_SEARCH_LOADED, _pattern_search_fn, _search_by_pattern_description_fn
    if _PATTERN_SEARCH_LOADED:
        return True
    try:
        from scripts.pattern_detection.search import (
            pattern_search,
            search_by_pattern_description,
        )
        _pattern_search_fn = pattern_search
        _search_by_pattern_description_fn = search_by_pattern_description
        _PATTERN_SEARCH_LOADED = True
        return True
    except ImportError as e:
        logger.warning(f"Pattern search not available: {e}")
        return False


# Supported languages for tree-sitter parsing (order matters - try common ones first)
_TREE_SITTER_LANGUAGES = [
    "python", "javascript", "typescript", "go", "rust", "java", "c", "cpp",
    "ruby", "php", "csharp", "kotlin", "swift", "scala", "bash", "lua",
]

# Fenced code block pattern (definitive - skip all other detection)
_FENCED_CODE = re.compile(r'^```\w*\n.*\n```$', re.DOTALL)

# NL exemplars for embedding comparison (lazy loaded)
# These should cover common search/query patterns
_NL_EXEMPLARS = [
    # Search queries
    "find code that handles authentication",
    "show me error handling patterns",
    "where is the database connection",
    "how does caching work",
    "how does the authentication system work",
    "what functions handle user input",
    "search for retry logic",
    "find similar code to this pattern",
    "list all API endpoints",
    "explain how this module works",
    "find code with exponential backoff",
    "find all tests for this module",
    "show me functions that process data",
    "get all logging code",
    "which class handles this",
    "functions like the one in utils",
    "examples of async await usage",
    # Short concept phrases
    "singleton implementation",
    "factory pattern",
    "observer pattern",
    "resource cleanup",
    "connection pooling",
    "rate limiting",
    "caching strategy",
    "input validation",
    "error handling",
    # Pattern descriptions
    "decorator pattern wrapping function",
    "retry with exponential backoff",
    "middleware pattern",
    "dependency injection",
    "builder pattern implementation",
]

# Embedding cache for NL detection
_NL_EMBEDDINGS_CACHE = None
_NL_EMBEDDINGS_LOCK = None

def _get_nl_embeddings_lock():
    """Lazy init threading lock."""
    global _NL_EMBEDDINGS_LOCK
    if _NL_EMBEDDINGS_LOCK is None:
        import threading
        _NL_EMBEDDINGS_LOCK = threading.Lock()
    return _NL_EMBEDDINGS_LOCK


def _try_parse_python_ast(text: str) -> bool:
    """Attempt to parse text as Python code using the ast module.

    Returns True if parsing succeeds (valid Python syntax).
    """
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        return False
    except Exception:
        return False


def _try_parse_with_tree_sitter(text: str, language: str) -> bool:
    """Attempt to parse text using tree-sitter for the given language.

    Returns True if parsing produces meaningful structure.
    For code fragments, tree-sitter may report has_error=True at root
    but still parse the content correctly, so we check for actual structure.
    """
    try:
        from scripts.ingest.tree_sitter import _ts_parser
        parser = _ts_parser(language)
        if not parser:
            return False
        tree = parser.parse(bytes(text, "utf-8"))
        if not tree or not tree.root_node:
            return False

        root = tree.root_node
        # No errors = successful parse
        if not root.has_error:
            return True

        # has_error=True at root - need to be careful
        # Tree-sitter tries to recover from errors, but we shouldn't trust
        # parses that are mostly ERROR nodes with trivial recovery
        error_count = 0
        meaningful_count = 0
        for child in root.children:
            if child.type == "ERROR" or child.has_error:
                error_count += 1
            elif child.type not in ("expression_statement", "identifier", "string"):
                # Meaningful node types (not just bare identifiers)
                meaningful_count += 1

        # Require more meaningful nodes than errors, or at least one
        # meaningful node with no errors
        if error_count == 0 and meaningful_count > 0:
            return True
        if meaningful_count > error_count:
            return True
        return False
    except ImportError:
        return False
    except Exception:
        return False


def _try_parse_any_language(text: str, hint: str | None = None) -> tuple[bool, str | None]:
    """Try parsing text with multiple language parsers.

    Returns (success, language) tuple. Tries hint language first if provided.
    """
    # Try Python AST first (fast, no dependencies)
    if _try_parse_python_ast(text):
        return True, "python"

    # Build language order - hint first, then common languages
    languages = []
    if hint and hint.lower() in _TREE_SITTER_LANGUAGES:
        languages.append(hint.lower())
    for lang in _TREE_SITTER_LANGUAGES:
        if lang not in languages:
            languages.append(lang)

    # Try tree-sitter parsers
    for lang in languages:
        if _try_parse_with_tree_sitter(text, lang):
            return True, lang

    return False, None


def _get_nl_exemplar_embeddings():
    """Get or compute cached NL exemplar embeddings."""
    global _NL_EMBEDDINGS_CACHE
    if _NL_EMBEDDINGS_CACHE is not None:
        return _NL_EMBEDDINGS_CACHE

    lock = _get_nl_embeddings_lock()
    with lock:
        if _NL_EMBEDDINGS_CACHE is not None:
            return _NL_EMBEDDINGS_CACHE

        try:
            from scripts.hybrid.embed import get_embedding_model
            embedder = get_embedding_model()
            embeddings = list(embedder.embed(_NL_EXEMPLARS))
            _NL_EMBEDDINGS_CACHE = embeddings
            logger.info(f"Cached {len(embeddings)} NL exemplar embeddings")
            return embeddings
        except Exception as e:
            logger.warning(f"Failed to compute NL exemplar embeddings: {e}")
            return None


def _compute_nl_similarity(text: str) -> float:
    """Compute max cosine similarity of text to NL exemplars.

    Returns similarity score 0.0-1.0. Higher = more likely NL.
    """
    exemplar_embeddings = _get_nl_exemplar_embeddings()
    if not exemplar_embeddings:
        return 0.5  # Neutral if embedder unavailable

    try:
        from scripts.hybrid.embed import get_embedding_model
        import numpy as np

        embedder = get_embedding_model()
        query_emb = list(embedder.embed([text]))[0]
        query_arr = np.array(query_emb)
        query_norm = np.linalg.norm(query_arr)

        if query_norm == 0:
            return 0.5

        max_sim = 0.0
        for ex_emb in exemplar_embeddings:
            ex_arr = np.array(ex_emb)
            ex_norm = np.linalg.norm(ex_arr)
            if ex_norm == 0:
                continue
            sim = float(np.dot(query_arr, ex_arr) / (query_norm * ex_norm))
            max_sim = max(max_sim, sim)

        return max(0.0, min(1.0, max_sim))
    except Exception as e:
        logger.warning(f"NL similarity computation failed: {e}")
        return 0.5


def _detect_query_mode_with_confidence(
    text: str,
    language: str | None = None,
    try_ast: bool = True,
) -> QueryModeResult:
    """
    Detect if text is code or natural language description.

    Strategy (AST + embedder fusion):
    1. Fenced code blocks → code (definitive)
    2. Try AST parsing (Python + tree-sitter)
    3. Use embedder similarity to NL exemplars
    4. Fuse signals: AST success + low NL similarity = code
       AST success + high NL similarity = check further (permissive langs like Ruby)

    Args:
        text: The query text to analyze
        language: Optional language hint for AST parsing
        try_ast: Whether to attempt AST parsing (default True)

    Returns:
        QueryModeResult with mode, confidence, and signal breakdown
    """
    text = text.strip()
    signals: Dict[str, float] = {}

    if not text:
        return QueryModeResult(
            mode="description",
            confidence=1.0,
            signals={"empty": 1.0},
            ast_validated=False,
        )

    # Step 1: Fenced code block (definitive)
    if _FENCED_CODE.match(text):
        return QueryModeResult(
            mode="code",
            confidence=1.0,
            signals={"fenced_block": 1.0},
            ast_validated=False,
        )

    # Step 2: AST parsing
    parsed = False
    parsed_lang = None
    if try_ast:
        parsed, parsed_lang = _try_parse_any_language(text, language)
        if parsed:
            signals["ast_parsed"] = 1.0
            signals["parsed_language"] = parsed_lang or "unknown"

    # Step 3: Embedder-based NL similarity
    nl_sim = _compute_nl_similarity(text)
    signals["nl_similarity"] = round(nl_sim, 3)

    # Step 4: Fuse AST and NL signals
    # Languages with permissive grammars (Ruby) parse NL as valid code
    permissive_langs = {"ruby", "bash", "lua"}
    is_permissive = parsed_lang in permissive_langs

    # AST parsed with trustworthy language + low NL → definitely code
    if parsed and not is_permissive and nl_sim < 0.65:
        return QueryModeResult(
            mode="code",
            confidence=0.95,
            signals=signals,
            ast_validated=True,
        )

    # AST parsed but need to check NL similarity for permissive languages
    if parsed:
        # Very high NL similarity (>0.9) = exact/near match to NL exemplar
        # This overrides AST parsing even for strict languages
        if nl_sim >= 0.9:
            return QueryModeResult(
                mode="description",
                confidence=min(1.0, 0.5 + nl_sim * 0.5),
                signals=signals,
                ast_validated=False,  # Don't trust AST for NL-like text
            )
        # High NL + permissive lang → description (catches phrases like "caching strategy")
        if is_permissive and nl_sim >= 0.65:
            return QueryModeResult(
                mode="description",
                confidence=0.8,
                signals=signals,
                ast_validated=False,
            )
        # AST parsed with lower/moderate NL → trust the AST
        return QueryModeResult(
            mode="code",
            confidence=0.85 if is_permissive else 0.95,
            signals=signals,
            ast_validated=True,
        )

    # No AST parse - rely on NL similarity
    if nl_sim >= 0.65:
        return QueryModeResult(
            mode="description",
            confidence=min(1.0, 0.5 + nl_sim * 0.5),
            signals=signals,
            ast_validated=False,
        )

    # Low NL similarity + no AST → likely code fragment
    return QueryModeResult(
        mode="code",
        confidence=min(1.0, 0.5 + (1.0 - nl_sim) * 0.4),
        signals=signals,
        ast_validated=False,
    )


def _detect_query_mode(text: str, language: str | None) -> str:
    """
    Auto-detect if text is code or natural language description.

    Works across all 16+ supported languages using universal syntax patterns.
    Returns: "code" or "description"

    Note: This is the legacy interface. For confidence scores, use
    _detect_query_mode_with_confidence() directly.
    """
    result = _detect_query_mode_with_confidence(text, language, try_ast=True)
    return result.mode


async def _pattern_search_impl(
    query: Optional[str] = None,
    language: Optional[str] = None,
    limit: Optional[int] = None,
    min_score: Optional[float] = None,
    include_snippet: Optional[bool] = None,
    context_lines: Optional[int] = None,
    hybrid: Optional[bool] = None,
    semantic_weight: Optional[float] = None,
    collection: Optional[str] = None,
    target_languages: Optional[List[str]] = None,
    repo: Optional[Union[str, List[str]]] = None,  # Filter by repo name(s) for scale
    output_format: Optional[str] = None,
    compact: Optional[bool] = None,
    aroma_rerank: Optional[bool] = None,
    aroma_alpha: Optional[float] = None,
    query_mode: Optional[str] = None,  # "code", "description", or "auto" (default)
    coerce_bool_fn=None,
    coerce_int_fn=None,
    coerce_float_fn=None,
) -> Dict[str, Any]:
    """Unified pattern search - handles both code examples and NL descriptions."""
    if not _ensure_pattern_search():
        return {"ok": False, "error": "Pattern search module not available"}

    if not query or not str(query).strip():
        return {"ok": False, "error": "query parameter is required"}

    query_text = str(query).strip()

    # Coerce parameters - handle string "false"/"0" correctly
    def _default_coerce_bool(v, d):
        if v is None:
            return d
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    def _safe_coerce_int(v, d):
        if v is None:
            return d
        try:
            return int(v)
        except (ValueError, TypeError):
            return d

    def _safe_coerce_float(v, d):
        if v is None:
            return d
        try:
            return float(v)
        except (ValueError, TypeError):
            return d

    _coerce_bool = coerce_bool_fn or _default_coerce_bool
    _coerce_int = coerce_int_fn or _safe_coerce_int
    _coerce_float = coerce_float_fn or _safe_coerce_float

    # Defaults aligned with core pattern_search API for consistent behavior
    eff_limit = _coerce_int(limit, 10)
    eff_include_snippet = _coerce_bool(include_snippet, True)
    eff_context_lines = _coerce_int(context_lines, 3)
    eff_hybrid = _coerce_bool(hybrid, False)
    eff_semantic_weight = _coerce_float(semantic_weight, 0.3)
    eff_compact = _coerce_bool(compact, False)
    eff_aroma_rerank = _coerce_bool(aroma_rerank, True)  # AROMA enabled by default
    eff_aroma_alpha = _coerce_float(aroma_alpha, 0.6)

    # Determine query mode: explicit override or auto-detect
    eff_language = str(language).strip() if language else None
    eff_query_mode = str(query_mode).strip().lower() if query_mode else "auto"

    # Track detection metadata for response
    detection_confidence: float = 1.0
    detection_signals: Dict[str, float] = {}
    detection_ast_validated: bool = False

    if eff_query_mode == "code":
        is_code = True
        detection_signals = {"explicit_override": 1.0}
    elif eff_query_mode == "description":
        is_code = False
        detection_signals = {"explicit_override": 1.0}
    else:  # auto - use enhanced detection with confidence
        detection_result = _detect_query_mode_with_confidence(
            query_text, eff_language, try_ast=True
        )
        is_code = (detection_result.mode == "code")
        detection_confidence = detection_result.confidence
        detection_signals = detection_result.signals
        detection_ast_validated = detection_result.ast_validated

    # Path-specific min_score defaults:
    # - Code path: 0.5 (vector similarity scores are typically higher)
    # - NL path: 0.0 (keyword overlap scores are often low, don't filter by default)
    eff_min_score = _coerce_float(min_score, 0.5 if is_code else 0.0)

    try:
        if is_code:
            # Structural pattern search using code example
            result = _pattern_search_fn(
                example=query_text,
                language=eff_language or "python",
                limit=eff_limit,
                min_score=eff_min_score,
                include_snippet=eff_include_snippet,
                context_lines=eff_context_lines,
                hybrid=eff_hybrid,
                semantic_weight=eff_semantic_weight,
                collection=collection,
                target_languages=target_languages,
                repo=repo,  # Pass through for scale (limits search to specific repos)
                output_format=output_format,
                compact=eff_compact,
                aroma_rerank=eff_aroma_rerank,
                aroma_alpha=eff_aroma_alpha,
            )
        else:
            # Natural language pattern description search
            result = _search_by_pattern_description_fn(
                description=query_text,
                limit=eff_limit,
                min_score=eff_min_score,
                collection=collection,
                target_languages=target_languages,
                repo=repo,
                output_format=output_format,
                compact=eff_compact,
            )

        # Convert response object to dict if needed
        if not isinstance(result, dict):
            result = result.to_dict()

        # Preserve upstream ok flag (derived from search_mode) instead of overriding
        # This ensures errors from core search propagate to MCP clients
        result["query_mode"] = "code" if is_code else "description"

        # Add detection metadata (useful for debugging and transparency)
        result["detection"] = {
            "confidence": round(detection_confidence, 3),
            "ast_validated": detection_ast_validated,
            "signals": {
                k: (round(v, 3) if isinstance(v, (int, float)) else v)
                for k, v in detection_signals.items()
            },
        }

        return result
    except Exception as e:
        logger.error(f"Pattern search failed: {e}")
        return {"ok": False, "error": str(e)}
