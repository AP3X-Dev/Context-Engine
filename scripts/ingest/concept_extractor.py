#!/usr/bin/env python3
"""
ingest/concept_extractor.py - Universal concept extraction using language mappings.

Extracts semantic concepts (DEFINITION, BLOCK, COMMENT, IMPORT, STRUCTURE)
from source code using the 34 language mappings with tree-sitter queries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node as TSNode, Tree, Language, Query, QueryCursor

logger = logging.getLogger(__name__)

try:
    from tree_sitter import Language, Query, QueryCursor
    TREE_SITTER_QUERY_AVAILABLE = True
except ImportError:
    TREE_SITTER_QUERY_AVAILABLE = False

from scripts.ingest.language_mappings import get_mapping, ConceptType, ConceptResult
from scripts.ingest.tree_sitter import _ts_parser, _use_tree_sitter, _TS_LANGUAGES


@dataclass
class ExtractedConcept:
    """A concept extracted from source code."""
    concept: ConceptType
    name: str
    content: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    kind: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def extract_concepts(
    content: str,
    language: str,
) -> List[ExtractedConcept]:
    """
    Extract semantic concepts from source code using language mappings.
    
    Uses tree-sitter queries from the 34 language mappings to find:
    - DEFINITION: functions, classes, methods, constants
    - BLOCK: control flow blocks, scoped regions
    - COMMENT: comments, docstrings
    - IMPORT: import/include statements
    - STRUCTURE: file-level structure
    
    Args:
        content: Source code content
        language: Programming language name
        
    Returns:
        List of ExtractedConcept objects sorted by start_line
    """
    if not content.strip():
        return []
    
    if not _use_tree_sitter():
        return _fallback_extract(content, language)
    
    mapping = get_mapping(language)
    if not mapping:
        return _fallback_extract(content, language)
    
    parser = _ts_parser(language)
    if not parser:
        return _fallback_extract(content, language)
    
    try:
        tree = parser.parse(content.encode("utf-8"))
        if tree is None:
            return _fallback_extract(content, language)
    except Exception as e:
        logger.debug(f"Tree-sitter parse failed for {language}: {e}")
        return _fallback_extract(content, language)
    
    concepts: List[ExtractedConcept] = []
    content_bytes = content.encode("utf-8")
    
    for concept_type in ConceptType:
        query_str = mapping.get_query_for_concept(concept_type)
        if not query_str:
            continue
        
        try:
            extracted = _run_concept_query(
                tree, query_str, content_bytes, content, 
                concept_type, mapping, language
            )
            concepts.extend(extracted)
        except Exception as e:
            logger.debug(f"Query failed for {concept_type.value} in {language}: {e}")
            continue
    
    concepts.sort(key=lambda c: (c.start_line, c.start_byte))
    
    return _deduplicate_concepts(concepts)


def _run_concept_query(
    tree: "Tree",
    query_str: str,
    content_bytes: bytes,
    content: str,
    concept_type: ConceptType,
    mapping: Any,
    language: str,
) -> List[ExtractedConcept]:
    """Run a tree-sitter query and extract concepts using QueryCursor API."""
    results: List[ExtractedConcept] = []
    
    if not TREE_SITTER_QUERY_AVAILABLE:
        return results
    
    try:
        ts_language = _TS_LANGUAGES.get(language)
        if ts_language is None:
            return results
        
        query = Query(ts_language, query_str)
        cursor = QueryCursor(query)
        
        processed_ranges: set = set()
        
        for match in cursor.matches(tree.root_node):
            pattern_idx, captures_dict = match
            
            main_node = None
            name_node = None
            
            for capture_name, nodes in captures_dict.items():
                if not nodes:
                    continue
                node = nodes[0]
                
                if capture_name in ("definition", "block", "import", "structure", 
                                   "comment", "module_docstring", "function_docstring",
                                   "class_docstring"):
                    main_node = node
                elif capture_name == "name":
                    name_node = node
            
            if main_node is None:
                continue
            
            range_key = (main_node.start_byte, main_node.end_byte)
            if range_key in processed_ranges:
                continue
            processed_ranges.add(range_key)
            
            node_content = content_bytes[main_node.start_byte:main_node.end_byte].decode("utf-8", errors="replace")
            
            if name_node:
                name = content_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
            else:
                name = _extract_name_from_node(main_node, content_bytes, mapping)
            
            kind = _infer_kind(main_node, concept_type)
            
            metadata = {}
            if concept_type == ConceptType.DEFINITION:
                metadata = _extract_definition_metadata(main_node, content_bytes, mapping)
            
            results.append(ExtractedConcept(
                concept=concept_type,
                name=name,
                content=node_content,
                start_line=main_node.start_point[0] + 1,
                end_line=main_node.end_point[0] + 1,
                start_byte=main_node.start_byte,
                end_byte=main_node.end_byte,
                kind=kind,
                metadata=metadata,
            ))
            
    except Exception as e:
        logger.debug(f"Query execution failed: {e}")
    
    return results


def _extract_name_from_node(node: "TSNode", content_bytes: bytes, mapping: Any) -> str:
    """Extract name from a tree-sitter node."""
    for i in range(node.child_count):
        child = node.child(i)
        if child and child.type == "identifier":
            return content_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        if child and child.type == "name":
            return content_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
    
    if hasattr(node, 'child_by_field_name'):
        name_node = node.child_by_field_name('name')
        if name_node:
            return content_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
    
    return f"{node.type}_{node.start_point[0] + 1}"


def _infer_kind(node: "TSNode", concept_type: ConceptType) -> str:
    """Infer the kind of symbol from node type."""
    node_type = node.type
    
    kind_map = {
        "function_definition": "function",
        "async_function_definition": "function",
        "function_declaration": "function",
        "arrow_function": "function",
        "method_definition": "method",
        "class_definition": "class",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
        "struct_item": "struct",
        "impl_item": "impl",
        "trait_item": "trait",
        "import_statement": "import",
        "import_from_statement": "import",
        "import_declaration": "import",
        "comment": "comment",
        "block_comment": "comment",
        "line_comment": "comment",
        "expression_statement": "constant",
        "assignment": "assignment",
        "if_statement": "if",
        "for_statement": "for",
        "while_statement": "while",
        "try_statement": "try",
        "with_statement": "with",
        "block": "block",
    }
    
    return kind_map.get(node_type, concept_type.value)


def _extract_definition_metadata(node: "TSNode", content_bytes: bytes, mapping: Any) -> Dict[str, Any]:
    """Extract rich metadata from definition nodes."""
    metadata: Dict[str, Any] = {}
    
    if hasattr(mapping, 'extract_parameters'):
        try:
            content = content_bytes.decode("utf-8", errors="replace")
            params = mapping.extract_parameters(node, content)
            if params:
                metadata["parameters"] = params
        except Exception:
            pass
    
    if hasattr(mapping, 'extract_decorators'):
        try:
            content = content_bytes.decode("utf-8", errors="replace")
            decorators = mapping.extract_decorators(node, content)
            if decorators:
                metadata["decorators"] = decorators
        except Exception:
            pass
    
    if hasattr(mapping, 'is_async'):
        try:
            content = content_bytes.decode("utf-8", errors="replace")
            if mapping.is_async(node, content):
                metadata["is_async"] = True
        except Exception:
            pass
    
    if hasattr(mapping, 'extract_inheritance'):
        try:
            content = content_bytes.decode("utf-8", errors="replace")
            inheritance = mapping.extract_inheritance(node, content)
            if inheritance:
                metadata["inherits"] = inheritance
        except Exception:
            pass
    
    return metadata


def _deduplicate_concepts(concepts: List[ExtractedConcept]) -> List[ExtractedConcept]:
    """Remove duplicate concepts (same range)."""
    seen: set = set()
    result: List[ExtractedConcept] = []
    
    for concept in concepts:
        key = (concept.start_byte, concept.end_byte, concept.concept.value)
        if key not in seen:
            seen.add(key)
            result.append(concept)
    
    return result


def _fallback_extract(content: str, language: str) -> List[ExtractedConcept]:
    """Fallback extraction using _extract_symbols when tree-sitter fails."""
    try:
        from scripts.ingest.symbols import _extract_symbols
        
        symbols = _extract_symbols(language, content)
        if not symbols:
            return []
        
        lines = content.splitlines()
        concepts: List[ExtractedConcept] = []
        
        for sym in symbols:
            start = sym.start or 1
            end = sym.end or start
            kind = getattr(sym, 'kind', 'unknown') or 'unknown'
            
            concept_type = _kind_to_concept(kind)
            sym_content = "\n".join(lines[start - 1:end])
            
            concepts.append(ExtractedConcept(
                concept=concept_type,
                name=sym.name or "",
                content=sym_content,
                start_line=start,
                end_line=end,
                kind=kind,
                metadata={
                    "parent": getattr(sym, 'parent', None),
                    "signature": getattr(sym, 'signature', None),
                    "docstring": getattr(sym, 'docstring', None),
                },
            ))
        
        return concepts
        
    except Exception as e:
        logger.debug(f"Fallback extraction failed: {e}")
        return []


def _kind_to_concept(kind: str) -> ConceptType:
    """Map symbol kind to concept type."""
    kind_lower = kind.lower()
    
    if kind_lower in ('function', 'method', 'class', 'type', 'interface', 
                      'enum', 'struct', 'trait', 'impl', 'const', 'constant',
                      'variable', 'property'):
        return ConceptType.DEFINITION
    if kind_lower in ('import', 'include', 'require', 'use'):
        return ConceptType.IMPORT
    if kind_lower in ('comment', 'docstring'):
        return ConceptType.COMMENT
    if kind_lower in ('block', 'if', 'for', 'while', 'try', 'with', 'match'):
        return ConceptType.BLOCK
    
    return ConceptType.STRUCTURE


def supported_languages() -> List[str]:
    """Get list of languages supported by concept extraction."""
    from scripts.ingest.language_mappings import supported_languages as lm_supported
    return lm_supported()
