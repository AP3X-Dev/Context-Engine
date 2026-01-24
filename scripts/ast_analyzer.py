#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Advanced AST-Based Code Understanding

Implements sophisticated code analysis using Abstract Syntax Trees (AST) for:
- Semantic-aware chunking (preserve function/class boundaries)
- Call graph extraction
- Import dependency analysis
- Type inference hints
- Cross-reference tracking
"""

import os
import re
import ast
import hashlib
import importlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger("ast_analyzer")

# ---------------------------------------------------------------------------
# Language Mappings Integration
# ---------------------------------------------------------------------------
# Context-Engine's unified concept-based extraction supporting 32 languages.
# Uses declarative tree-sitter queries organized by semantic concept type:
#   DEFINITION, BLOCK, COMMENT, IMPORT, STRUCTURE
_LANGUAGE_MAPPINGS_AVAILABLE = False
try:
    from scripts.ingest.language_mappings import get_mapping, supported_languages as lm_supported_languages, ConceptType
    _LANGUAGE_MAPPINGS_AVAILABLE = True
except ImportError:
    pass

# Optional tree-sitter support - tree-sitter 0.25+ API
_TS_LANGUAGES: Dict[str, Any] = {}
_TS_AVAILABLE = False
try:
    from tree_sitter import Parser, Language

    def _load_ts_language(mod: Any, *, preferred: list[str] | None = None) -> Any | None:
        """Return a tree-sitter Language instance from a per-language package.

        Different packages expose different entrypoints (e.g. language(),
        language_typescript(), language_tsx()).
        """
        preferred = preferred or []
        candidates: list[Any] = []
        if getattr(mod, "language", None) is not None and callable(getattr(mod, "language")):
            candidates.append(getattr(mod, "language"))
        for name in preferred:
            fn = getattr(mod, name, None)
            if fn is not None and callable(fn):
                candidates.append(fn)
        # Last resort: scan for any callable language* attribute
        for name in dir(mod):
            if not name.startswith("language"):
                continue
            fn = getattr(mod, name, None)
            if fn is not None and callable(fn):
                candidates.append(fn)

        for fn in candidates:
            try:
                raw_lang = fn()
                return raw_lang if isinstance(raw_lang, Language) else Language(raw_lang)
            except Exception as e:
                logger.debug(f"Suppressed exception, continuing: {e}")
                continue
        return None

    # Import all available language packages
    for lang_name, pkg_name in [
        ("python", "tree_sitter_python"),
        ("javascript", "tree_sitter_javascript"),
        ("typescript", "tree_sitter_typescript"),
        ("go", "tree_sitter_go"),
        ("rust", "tree_sitter_rust"),
        ("java", "tree_sitter_java"),
        ("c", "tree_sitter_c"),
        ("cpp", "tree_sitter_cpp"),
        ("ruby", "tree_sitter_ruby"),
        ("c_sharp", "tree_sitter_c_sharp"),
        ("bash", "tree_sitter_bash"),
        ("json", "tree_sitter_json"),
        ("yaml", "tree_sitter_yaml"),
        ("html", "tree_sitter_html"),
        ("css", "tree_sitter_css"),
        ("markdown", "tree_sitter_markdown"),
    ]:
        try:
            mod = __import__(pkg_name)
            preferred: list[str] = []
            if lang_name == "typescript":
                preferred = ["language_typescript"]
            elif lang_name == "c_sharp":
                preferred = ["language_c_sharp", "language_csharp"]
            lang = _load_ts_language(mod, preferred=preferred)
            if lang is not None:
                _TS_LANGUAGES[lang_name] = lang
                # Also load TSX if provided by the typescript package
                if lang_name == "typescript":
                    tsx_lang = _load_ts_language(mod, preferred=["language_tsx"])
                    if tsx_lang is not None:
                        _TS_LANGUAGES["tsx"] = tsx_lang
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")  # Language package not installed

    # Add aliases
    if "javascript" in _TS_LANGUAGES:
        _TS_LANGUAGES["jsx"] = _TS_LANGUAGES["javascript"]
    if "c_sharp" in _TS_LANGUAGES:
        _TS_LANGUAGES["csharp"] = _TS_LANGUAGES["c_sharp"]
    if "bash" in _TS_LANGUAGES:
        _TS_LANGUAGES["shell"] = _TS_LANGUAGES["bash"]
        _TS_LANGUAGES["sh"] = _TS_LANGUAGES["bash"]

    _TS_AVAILABLE = len(_TS_LANGUAGES) > 0
except Exception:
    Parser = None
    Language = None
    _TS_LANGUAGES = {}
    _TS_AVAILABLE = False


@dataclass
class CodeSymbol:
    """Represents a code symbol (function, class, method, etc)."""
    name: str
    kind: str  # function, class, method, interface, etc.
    start_line: int
    end_line: int
    path: Optional[str] = None  # Fully qualified path (e.g., "MyClass.method")
    docstring: Optional[str] = None
    signature: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    parent: Optional[str] = None  # Parent class/module
    complexity: int = 0  # Cyclomatic complexity estimate
    content_hash: Optional[str] = None
    concept: Optional[str] = None  # Universal concept type (definition, block, comment, etc.)


@dataclass
class ConceptUnit:
    """A semantic code unit with universal concept classification.
    
    Context-Engine's 5 universal concepts for language-agnostic analysis:
    - DEFINITION: functions, classes, types, constants
    - BLOCK: control flow, scoped regions
    - COMMENT: comments, docstrings
    - IMPORT: import/include statements
    - STRUCTURE: file-level organization
    """
    concept: str  # definition, block, comment, import, structure
    name: str
    content: str
    start_line: int
    end_line: int
    kind: str = ""  # More specific: function, class, if, for, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CallReference:
    """Represents a function/method call."""
    caller: str  # Who is calling
    callee: str  # What is being called
    line: int
    context: str  # e.g., "function", "method", "module"


@dataclass
class ImportReference:
    """Represents an import statement."""
    module: str
    names: List[str]  # Specific imports (empty if import *)
    line: int
    alias: Optional[str] = None
    is_from: bool = False


@dataclass
class CodeContext:
    """Complete context for a code chunk."""
    chunk_text: str
    start_line: int
    end_line: int
    symbols: List[CodeSymbol]
    imports: List[ImportReference]
    calls: List[CallReference]
    dependencies: Set[str]  # Modules/files this depends on
    is_semantic_unit: bool = True  # True if chunk respects boundaries


class ASTAnalyzer:
    """
    Advanced AST-based code analyzer for semantic understanding.
    
    Features:
    - Language-aware symbol extraction
    - Call graph construction
    - Dependency tracking
    - Semantic chunking (preserve boundaries)
    - Cross-reference analysis
    """
    
    def __init__(self, use_tree_sitter: bool = True):
        """
        Initialize AST analyzer.
        
        Args:
            use_tree_sitter: Use tree-sitter when available (fallback to ast module)
        """
        self.use_tree_sitter = use_tree_sitter and _TS_AVAILABLE
        self._parsers: Dict[str, Any] = {}
        
        # Language support matrix
        self.supported_languages = {
            "python": {"ast": True, "tree_sitter": True},
            "javascript": {"ast": False, "tree_sitter": True},
            "typescript": {"ast": False, "tree_sitter": True},
            "java": {"ast": False, "tree_sitter": True},
            "go": {"ast": False, "tree_sitter": True},
            "rust": {"ast": False, "tree_sitter": True},
            "c": {"ast": False, "tree_sitter": True},
            "cpp": {"ast": False, "tree_sitter": True},
            "ruby": {"ast": False, "tree_sitter": True},
        }
        
        logger.info(f"ASTAnalyzer initialized: tree_sitter={self.use_tree_sitter}")
    
    def analyze_file(
        self, file_path: str, language: str, content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze a source file and extract semantic information.
        
        Args:
            file_path: Path to the file
            language: Programming language
            content: Optional file content (if not provided, read from file)
        
        Returns:
            Dict with symbols, imports, calls, and dependencies
        """
        if content is None:
            try:
                content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.error(f"Failed to read {file_path}: {e}")
                return self._empty_analysis()
        
        # Use language mappings (32 languages, declarative queries)
        if _LANGUAGE_MAPPINGS_AVAILABLE and self.use_tree_sitter:
            result = self._analyze_with_mapping(content, file_path, language)
            if result and (result.get("symbols") or result.get("imports") or result.get("calls")):
                return result
        
        # Fallback to legacy per-language analyzers
        if language == "python":
            return self._analyze_python(content, file_path)
        elif language in ("javascript", "typescript") and self.use_tree_sitter:
            return self._analyze_js_ts(content, file_path, language)
        elif language == "go" and self.use_tree_sitter:
            return self._analyze_go(content, file_path)
        elif language == "rust" and self.use_tree_sitter:
            return self._analyze_rust(content, file_path)
        elif language == "java" and self.use_tree_sitter:
            return self._analyze_java(content, file_path)
        elif language in ("c", "cpp") and self.use_tree_sitter:
            return self._analyze_c_cpp(content, file_path, language)
        elif language == "ruby" and self.use_tree_sitter:
            return self._analyze_ruby(content, file_path)
        else:
            # Fallback to regex-based analysis
            return self._analyze_generic(content, file_path, language)
    
    def extract_symbols_with_context(
        self, file_path: str, language: str, content: Optional[str] = None
    ) -> List[CodeSymbol]:
        """
        Extract code symbols with full context (docstrings, signatures, etc).
        
        Returns:
            List of CodeSymbol objects with rich metadata
        """
        analysis = self.analyze_file(file_path, language, content)
        return analysis.get("symbols", [])
    
    def chunk_semantic(
        self,
        content: str,
        language: str,
        max_lines: int = 120,
        overlap_lines: int = 20,
        preserve_boundaries: bool = True
    ) -> List[CodeContext]:
        """
        Chunk code semantically, respecting function/class boundaries.
        
        Args:
            content: Source code content
            language: Programming language
            max_lines: Maximum lines per chunk
            overlap_lines: Overlap between chunks
            preserve_boundaries: Try to keep complete functions/classes together
        
        Returns:
            List of CodeContext objects with semantic chunks
        """
        if not preserve_boundaries:
            # Fall back to line-based chunking
            return self._chunk_lines_simple(content, max_lines, overlap_lines)
        
        # Extract symbols
        analysis = self.analyze_file("", language, content)
        symbols = analysis.get("symbols", [])
        
        if not symbols:
            # No symbols found, use line-based
            return self._chunk_lines_simple(content, max_lines, overlap_lines)
        
        lines = content.splitlines()
        chunks = []
        
        # Sort symbols by start line
        symbols.sort(key=lambda s: s.start_line)
        
        i = 0
        while i < len(symbols):
            symbol = symbols[i]
            
            # Calculate chunk extent
            chunk_start = symbol.start_line
            chunk_end = symbol.end_line
            symbols_in_chunk = [symbol]
            
            # Try to include adjacent small symbols
            j = i + 1
            while j < len(symbols):
                next_symbol = symbols[j]
                potential_end = next_symbol.end_line
                
                # Check if adding next symbol exceeds max_lines
                if potential_end - chunk_start > max_lines:
                    break
                
                # Check if next symbol is close enough (within overlap)
                if next_symbol.start_line - chunk_end > overlap_lines:
                    break
                
                # Include this symbol
                chunk_end = potential_end
                symbols_in_chunk.append(next_symbol)
                j += 1
            
            # Create chunk
            chunk_lines = lines[chunk_start - 1:chunk_end]
            chunk_text = "\n".join(chunk_lines)
            
            # Extract chunk-specific imports and calls
            chunk_imports = [
                imp for imp in analysis.get("imports", [])
                if chunk_start <= imp.line <= chunk_end
            ]
            chunk_calls = [
                call for call in analysis.get("calls", [])
                if chunk_start <= call.line <= chunk_end
            ]
            
            context = CodeContext(
                chunk_text=chunk_text,
                start_line=chunk_start,
                end_line=chunk_end,
                symbols=symbols_in_chunk,
                imports=chunk_imports,
                calls=chunk_calls,
                dependencies=self._extract_dependencies(chunk_imports, chunk_calls),
                is_semantic_unit=True
            )
            
            chunks.append(context)
            i = j if j > i else i + 1
        
        # Handle code not covered by symbols (module-level code, etc)
        self._fill_gaps(chunks, lines, max_lines, overlap_lines, analysis)
        
        return chunks
    
    def build_call_graph(self, file_path: str, language: str) -> Dict[str, List[str]]:
        """
        Build call graph: mapping of caller -> list of callees.
        
        Returns:
            Dict mapping function names to list of functions they call
        """
        analysis = self.analyze_file(file_path, language)
        
        call_graph = defaultdict(list)
        for call in analysis.get("calls", []):
            call_graph[call.caller].append(call.callee)
        
        return dict(call_graph)
    
    def extract_dependencies(
        self, file_path: str, language: str
    ) -> Dict[str, List[str]]:
        """
        Extract file dependencies (imports, includes).
        
        Returns:
            Dict with 'modules' (external) and 'local' (same project) imports
        """
        analysis = self.analyze_file(file_path, language)
        imports = analysis.get("imports", [])
        
        modules = []
        local = []
        
        for imp in imports:
            # Simple heuristic: relative imports or without dots are likely local
            if imp.module.startswith(".") or "/" in imp.module:
                local.append(imp.module)
            else:
                modules.append(imp.module)
        
        return {
            "modules": list(set(modules)),
            "local": list(set(local))
        }
    
    # ---- Language Mappings Analysis (unified, concept-based) ----
    
    def _analyze_with_mapping(self, content: str, file_path: str, language: str) -> Dict[str, Any]:
        """Analyze code using language mappings (concept-based extraction).
        
        This uses the declarative tree-sitter queries from language_mappings
        to extract symbols, imports, and calls. Supports 34 languages.
        """
        if not _LANGUAGE_MAPPINGS_AVAILABLE:
            return self._empty_analysis()
        
        try:
            mapping = get_mapping(language)
        except (TypeError, Exception) as e:
            logger.debug(f"Mapping instantiation failed for {language}: {e}")
            return self._empty_analysis()
        
        if not mapping:
            return self._empty_analysis()
        
        # Get parser for this language
        parser = self._get_ts_parser(language)
        if not parser:
            return self._empty_analysis()
        
        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.debug(f"Tree-sitter parse failed for {language}: {e}")
            return self._empty_analysis()
        
        content_bytes = content.encode("utf-8")
        symbols: List[CodeSymbol] = []
        imports: List[ImportReference] = []
        calls: List[CallReference] = []
        
        # Get tree-sitter language object for queries
        ts_lang = _TS_LANGUAGES.get(language) or _TS_LANGUAGES.get(self._normalize_lang(language))
        if not ts_lang:
            return self._empty_analysis()
        
        try:
            from tree_sitter import Query, QueryCursor
        except ImportError:
            return self._empty_analysis()
        
        # Extract DEFINITION concepts -> symbols
        def_query_str = mapping.get_query_for_concept(ConceptType.DEFINITION)
        if def_query_str:
            try:
                query = Query(ts_lang, def_query_str)
                cursor = QueryCursor(query)
                seen_ranges: Set[Tuple[int, int]] = set()
                
                for match in cursor.matches(root):
                    _, captures_dict = match
                    main_node = None
                    name_node = None
                    
                    for capture_name, nodes in captures_dict.items():
                        if not nodes:
                            continue
                        node = nodes[0]
                        if capture_name in ("definition", "function_def", "class_def", 
                                           "method_def", "type_def", "const_def"):
                            main_node = node
                        elif capture_name in ("name", "function_name", "class_name", 
                                             "method_name", "type_name", "const_name"):
                            name_node = node
                        elif main_node is None:
                            main_node = node
                    
                    if main_node is None:
                        continue
                    
                    range_key = (main_node.start_byte, main_node.end_byte)
                    if range_key in seen_ranges:
                        continue
                    seen_ranges.add(range_key)
                    
                    # Extract name
                    if name_node:
                        name = content_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    else:
                        name = self._extract_name_from_ts_node(main_node, content_bytes)
                    
                    # Infer kind from node type
                    kind = self._node_type_to_kind(main_node.type)
                    
                    # Extract docstring if available
                    docstring = self._extract_ts_docstring(main_node, content_bytes)
                    
                    # Extract signature
                    signature = self._extract_ts_signature(main_node, content_bytes, name, kind)
                    
                    # Extract decorators (for Python, etc.)
                    decorators = self._extract_ts_decorators(main_node, content_bytes)
                    
                    # Determine parent
                    parent = self._find_ts_parent_name(main_node, content_bytes)
                    
                    symbols.append(CodeSymbol(
                        name=name,
                        kind=kind,
                        start_line=main_node.start_point[0] + 1,
                        end_line=main_node.end_point[0] + 1,
                        path=f"{parent}.{name}" if parent else name,
                        docstring=docstring,
                        signature=signature,
                        decorators=decorators,
                        parent=parent,
                    ))
            except Exception as e:
                logger.debug(f"DEFINITION query failed for {language}: {e}")
        
        # Extract IMPORT concepts -> imports
        import_query_str = mapping.get_query_for_concept(ConceptType.IMPORT)
        if import_query_str:
            try:
                query = Query(ts_lang, import_query_str)
                cursor = QueryCursor(query)
                seen_ranges: Set[Tuple[int, int]] = set()
                
                for match in cursor.matches(root):
                    _, captures_dict = match
                    main_node = None
                    path_node = None
                    
                    for capture_name, nodes in captures_dict.items():
                        if not nodes:
                            continue
                        node = nodes[0]
                        # Look for import path specifically
                        if capture_name in ("import_path", "path", "module", "source"):
                            path_node = node
                        # Look for import statement container
                        elif capture_name in ("import", "import_from", "import_statement", 
                                             "import_spec", "import_declaration",
                                             "include", "require", "use", "definition"):
                            if main_node is None or node.start_byte < main_node.start_byte:
                                main_node = node
                    
                    # Use path_node if available for cleaner import text
                    import_node = path_node or main_node
                    if import_node is None:
                        continue
                    
                    range_key = (import_node.start_byte, import_node.end_byte)
                    if range_key in seen_ranges:
                        continue
                    seen_ranges.add(range_key)
                    
                    import_text = content_bytes[import_node.start_byte:import_node.end_byte].decode("utf-8", errors="replace")
                    module, names, is_from = self._parse_import_text(import_text, language)
                    
                    # If path_node was used directly, the text might be just the path
                    if not module and path_node:
                        module = import_text.strip().strip('"\'')
                    
                    if module:
                        imports.append(ImportReference(
                            module=module,
                            names=names,
                            line=import_node.start_point[0] + 1,
                            is_from=is_from,
                        ))
            except Exception as e:
                logger.debug(f"IMPORT query failed for {language}: {e}")
        
        # Extract calls by walking the tree for call expressions
        calls = self._extract_calls_from_tree(root, content_bytes, symbols, language)
        
        # Extract all concepts for comprehensive analysis
        concepts: List[ConceptUnit] = []
        for concept_type in ConceptType:
            query_str = mapping.get_query_for_concept(concept_type)
            if not query_str:
                continue
            try:
                query = Query(ts_lang, query_str)
                cursor = QueryCursor(query)
                seen: Set[Tuple[int, int]] = set()
                
                for match in cursor.matches(root):
                    _, captures_dict = match
                    main_node = None
                    name_node = None
                    
                    for cname, nodes in captures_dict.items():
                        if not nodes:
                            continue
                        node = nodes[0]
                        if cname in ("definition", "block", "import", "comment", "structure"):
                            main_node = node
                        elif cname == "name" or cname.endswith("_name"):
                            name_node = node
                        elif main_node is None:
                            main_node = node
                    
                    if main_node is None:
                        continue
                    
                    rkey = (main_node.start_byte, main_node.end_byte)
                    if rkey in seen:
                        continue
                    seen.add(rkey)
                    
                    if name_node:
                        name = content_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    else:
                        name = self._extract_name_from_ts_node(main_node, content_bytes)
                    
                    unit_content = content_bytes[main_node.start_byte:main_node.end_byte].decode("utf-8", errors="replace")
                    
                    concepts.append(ConceptUnit(
                        concept=concept_type.value,
                        name=name,
                        content=unit_content,
                        start_line=main_node.start_point[0] + 1,
                        end_line=main_node.end_point[0] + 1,
                        kind=self._node_type_to_kind(main_node.type),
                    ))
            except Exception as e:
                logger.debug(f"{concept_type.value} query failed for {language}: {e}")
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "concepts": concepts,  # All semantic units by concept type
            "language": language,
        }
    
    def _normalize_lang(self, language: str) -> str:
        """Normalize language name to tree-sitter key."""
        lang = language.lower().strip()
        aliases = {
            "js": "javascript", "jsx": "javascript",
            "ts": "typescript", "tsx": "typescript",
            "c++": "cpp", "cxx": "cpp",
            "c#": "csharp", "cs": "csharp",
            "shell": "bash", "sh": "bash",
        }
        return aliases.get(lang, lang)
    
    def _extract_name_from_ts_node(self, node, content_bytes: bytes) -> str:
        """Extract name from tree-sitter node."""
        # Try field 'name' first
        if hasattr(node, 'child_by_field_name'):
            name_node = node.child_by_field_name('name')
            if name_node:
                return content_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
        
        # Look for identifier child
        for i in range(node.child_count):
            child = node.child(i)
            if child and child.type in ("identifier", "name", "type_identifier"):
                return content_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        
        return f"anonymous_{node.start_point[0] + 1}"
    
    def _node_type_to_kind(self, node_type: str) -> str:
        """Map tree-sitter node type to symbol kind."""
        mapping = {
            # Functions
            "function_definition": "function",
            "async_function_definition": "function",
            "function_declaration": "function",
            "arrow_function": "function",
            "function_item": "function",
            "generator_function_declaration": "function",
            # Methods
            "method_definition": "method",
            "method_declaration": "method",
            # Classes
            "class_definition": "class",
            "class_declaration": "class",
            "class_specifier": "class",
            # Structs (Go, Rust, C/C++)
            "struct_item": "struct",
            "struct_specifier": "struct",
            "type_declaration": "struct",  # Go uses this for struct/interface
            "type_spec": "struct",
            # Interfaces
            "interface_declaration": "interface",
            "interface_type": "interface",
            # Types
            "type_alias_declaration": "type",
            "type_item": "type",
            # Enums
            "enum_declaration": "enum",
            "enum_item": "enum",
            # Rust-specific
            "impl_item": "impl",
            "trait_item": "trait",
            "mod_item": "module",
            # Constants/Variables
            "const_item": "constant",
            "const_declaration": "constant",
            "variable_declaration": "variable",
            "lexical_declaration": "variable",
            # Imports
            "import_statement": "import",
            "import_declaration": "import",
            "import_spec": "import",
            # Comments
            "comment": "comment",
            "block_comment": "comment",
            "line_comment": "comment",
            # Control flow (for BLOCK concepts)
            "if_statement": "if",
            "for_statement": "for",
            "while_statement": "while",
            "try_statement": "try",
            "switch_statement": "switch",
            "match_expression": "match",
        }
        return mapping.get(node_type, "symbol")
    
    def _extract_ts_docstring(self, node, content_bytes: bytes) -> Optional[str]:
        """Extract docstring from node body."""
        body = node.child_by_field_name('body') if hasattr(node, 'child_by_field_name') else None
        if not body:
            return None
        
        for i in range(min(2, body.child_count)):
            child = body.child(i)
            if child and child.type == "expression_statement":
                for j in range(child.child_count):
                    expr = child.child(j)
                    if expr and expr.type == "string":
                        text = content_bytes[expr.start_byte:expr.end_byte].decode("utf-8", errors="replace")
                        # Strip quotes
                        if text.startswith('"""') or text.startswith("'''"):
                            return text[3:-3].strip()
                        elif text.startswith('"') or text.startswith("'"):
                            return text[1:-1].strip()
        return None
    
    def _extract_ts_signature(self, node, content_bytes: bytes, name: str, kind: str) -> str:
        """Build signature from node."""
        if kind in ("function", "method"):
            params_node = node.child_by_field_name('parameters') if hasattr(node, 'child_by_field_name') else None
            if params_node:
                params_text = content_bytes[params_node.start_byte:params_node.end_byte].decode("utf-8", errors="replace")
                return f"def {name}{params_text}"
            return f"def {name}()"
        elif kind == "class":
            return f"class {name}"
        return name
    
    def _extract_ts_decorators(self, node, content_bytes: bytes) -> List[str]:
        """Extract decorators from preceding siblings."""
        decorators = []
        prev = node.prev_sibling
        while prev and prev.type == "decorator":
            dec_text = content_bytes[prev.start_byte:prev.end_byte].decode("utf-8", errors="replace")
            dec_name = dec_text.lstrip("@").split("(")[0]
            decorators.insert(0, dec_name)
            prev = prev.prev_sibling
        return decorators
    
    def _find_ts_parent_name(self, node, content_bytes: bytes) -> Optional[str]:
        """Find parent class/module name."""
        parent = node.parent
        while parent:
            if parent.type in ("class_definition", "class_declaration", "class_specifier",
                              "impl_item", "module"):
                name_node = parent.child_by_field_name('name') if hasattr(parent, 'child_by_field_name') else None
                if name_node:
                    return content_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
            parent = parent.parent
        return None
    
    def _parse_import_text(self, text: str, language: str) -> Tuple[str, List[str], bool]:
        """Parse import statement text to extract module and names."""
        text = text.strip()
        
        # Python: from X import Y or import X
        if language == "python":
            if text.startswith("from "):
                match = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", text)
                if match:
                    module = match.group(1)
                    names_str = match.group(2)
                    names = [n.strip().split(" as ")[0] for n in names_str.split(",")]
                    return module, names, True
            elif text.startswith("import "):
                modules_part = text[7:].strip()
                modules = [m.strip().split(" as ")[0].strip() for m in modules_part.split(",")]
                if modules:
                    return modules[0], modules[1:] if len(modules) > 1 else [], False
        
        # JavaScript/TypeScript: import X from 'Y' or require('Y')
        elif language in ("javascript", "typescript", "jsx", "tsx"):
            if "from" in text:
                match = re.search(r"from\s+['\"]([^'\"]+)['\"]", text)
                if match:
                    return match.group(1), [], True
            elif "require" in text:
                match = re.search(r"require\s*\(\s*['\"]([^'\"]+)['\"]", text)
                if match:
                    return match.group(1), [], False
        
        # Go: import "path"
        elif language == "go":
            match = re.search(r'"([^"]+)"', text)
            if match:
                return match.group(1), [], False
        
        # Rust: use path::to::module
        elif language == "rust":
            match = re.match(r"use\s+([\w:]+)", text)
            if match:
                return match.group(1), [], False
        
        # Java/Kotlin: import package.Class;
        elif language in ("java", "kotlin"):
            match = re.match(r"import\s+([\w.]+);?", text)
            if match:
                return match.group(1), [], False
        
        # C/C++: #include <header> or #include "header"
        elif language in ("c", "cpp"):
            match = re.search(r'#include\s*[<"]([^>"]+)[>"]', text)
            if match:
                return match.group(1), [], False
        
        # C#: using Namespace;
        elif language == "csharp":
            match = re.match(r"using\s+([\w.]+);?", text)
            if match:
                return match.group(1), [], False
        
        # Generic: try to find quoted string
        match = re.search(r"['\"]([^'\"]+)['\"]", text)
        if match:
            return match.group(1), [], False
        
        return "", [], False
    
    def _extract_calls_from_tree(self, root, content_bytes: bytes, symbols: List[CodeSymbol], language: str) -> List[CallReference]:
        """Walk tree to extract function calls."""
        calls: List[CallReference] = []
        symbol_ranges = [(s.start_line, s.end_line, s.path or s.name) for s in symbols]
        
        def find_enclosing_symbol(line: int) -> str:
            best_match = ""
            best_span = float("inf")
            for start, end, path in symbol_ranges:
                if start <= line <= end:
                    span = end - start
                    if span < best_span:
                        best_span = span
                        best_match = path
            return best_match
        
        def walk(node):
            node_type = node.type
            
            # Call expressions
            if node_type in ("call", "call_expression", "function_call", "method_call"):
                func_node = node.child_by_field_name('function') if hasattr(node, 'child_by_field_name') else None
                if not func_node:
                    # Try first child
                    for i in range(node.child_count):
                        child = node.child(i)
                        if child and child.type in ("identifier", "member_expression", "attribute"):
                            func_node = child
                            break
                
                if func_node:
                    callee = content_bytes[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="replace")
                    # Clean up callee (get last part of attribute access)
                    if "." in callee:
                        callee = callee.split(".")[-1]
                    
                    line = node.start_point[0] + 1
                    caller = find_enclosing_symbol(line)
                    
                    calls.append(CallReference(
                        caller=caller,
                        callee=callee,
                        line=line,
                        context="call",
                    ))
            
            # Recurse
            for i in range(node.child_count):
                child = node.child(i)
                if child:
                    walk(child)
        
        walk(root)
        return calls

    # ---- Python-specific analysis (using ast module) ----

    def _analyze_python(self, content: str, file_path: str) -> Dict[str, Any]:
        """Analyze Python code. Prefers tree-sitter, falls back to ast module."""
        # Prefer tree-sitter: handles Python 2/3, no SyntaxWarnings for escape sequences
        if self.use_tree_sitter and "python" in _TS_LANGUAGES:
            return self._analyze_python_treesitter(content, file_path)
        
        # Fallback to ast module (may emit SyntaxWarnings on Python 3.12+ for invalid escapes)
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            # Python 2 code can't be parsed by Python 3's ast module
            # Fall back to tree-sitter which handles both Python 2 and 3
            if self.use_tree_sitter and "python" in _TS_LANGUAGES:
                logger.debug(f"Falling back to tree-sitter for Python 2 code in {file_path}: {e}")
                return self._analyze_python_treesitter(content, file_path)
            logger.warning(f"Python syntax error in {file_path}: {e}")
            return self._empty_analysis()
        
        symbols = []
        imports = []
        calls = []

        class _PyAnalyzer(ast.NodeVisitor):
            def __init__(self, outer: "ASTAnalyzer"):
                self.outer = outer
                self.class_stack: list[str] = []
                self.func_stack: list[str] = []

            def _current_func_path(self) -> str:
                if not self.func_stack:
                    return ""
                parts: list[str] = []
                if self.class_stack:
                    parts.extend(self.class_stack)
                parts.extend(self.func_stack)
                return ".".join(parts)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                class_name = node.name
                class_path = ".".join(self.class_stack + [class_name])
                symbols.append(
                    self.outer._extract_python_class(
                        node, content, path=class_path
                    )
                )
                self.class_stack.append(class_name)
                self.generic_visit(node)
                self.class_stack.pop()

            def _visit_function(self, node: ast.AST) -> None:
                name = getattr(node, "name", "")
                prefix = self.class_stack + self.func_stack
                path = ".".join(prefix + ([name] if name else []))
                parent = None
                if self.func_stack:
                    parent = self.func_stack[-1]
                elif self.class_stack:
                    parent = self.class_stack[-1]

                kind = "method" if self.class_stack else "function"
                symbols.append(
                    self.outer._extract_python_function(
                        node, content, kind=kind, path=path, parent=parent
                    )
                )
                if name:
                    self.func_stack.append(name)
                    self.generic_visit(node)
                    self.func_stack.pop()
                else:
                    self.generic_visit(node)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._visit_function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._visit_function(node)

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names:
                    imports.append(
                        ImportReference(
                            module=alias.name,
                            names=[],
                            alias=alias.asname,
                            line=node.lineno,
                            is_from=False,
                        )
                    )

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                names = [alias.name for alias in node.names]
                imports.append(
                    ImportReference(
                        module=node.module or "",
                        names=names,
                        alias=None,
                        line=node.lineno,
                        is_from=True,
                    )
                )

            def visit_Call(self, node: ast.Call) -> None:
                callee = self.outer._get_call_name(node.func)
                if callee:
                    calls.append(
                        CallReference(
                            caller=self._current_func_path(),
                            callee=callee,
                            line=getattr(node, "lineno", 0),
                            context="call",
                        )
                    )
                self.generic_visit(node)

        _PyAnalyzer(self).visit(tree)
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": "python"
        }
    
    def _extract_python_function(
        self,
        node: ast.AST,
        content: str,
        *,
        kind: str,
        path: str,
        parent: Optional[str],
    ) -> CodeSymbol:
        """Extract detailed function information from AST node."""
        # Get docstring
        docstring = ast.get_docstring(node)
        
        # Get decorators
        decorators = [self._get_decorator_name(d) for d in node.decorator_list]
        
        # Build signature
        args = [arg.arg for arg in node.args.args]
        signature = f"def {node.name}({', '.join(args)})"
        
        # Calculate complexity (simplified: count branches)
        complexity = sum(
            1 for n in ast.walk(node)
            if isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.With))
        )
        
        # Content hash
        lines = content.splitlines()
        if node.lineno <= len(lines) and node.end_lineno <= len(lines):
            func_content = "\n".join(lines[node.lineno - 1:node.end_lineno])
            content_hash = hashlib.md5(func_content.encode()).hexdigest()[:8]
        else:
            content_hash = None
        
        return CodeSymbol(
            name=getattr(node, "name", ""),
            kind=kind,
            start_line=getattr(node, "lineno", 0),
            end_line=getattr(node, "end_lineno", getattr(node, "lineno", 0)) or 0,
            docstring=docstring,
            signature=signature,
            decorators=decorators,
            complexity=complexity,
            content_hash=content_hash,
            path=path,
            parent=parent,
        )
    
    def _extract_python_class(
        self, node: ast.ClassDef, content: str, *, path: Optional[str] = None
    ) -> CodeSymbol:
        """Extract detailed class information from AST node."""
        docstring = ast.get_docstring(node)
        decorators = [self._get_decorator_name(d) for d in node.decorator_list]
        
        # Get base classes
        bases = [self._get_name(base) for base in node.bases]
        signature = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
        
        # Count methods
        methods = sum(
            1 for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        
        return CodeSymbol(
            name=node.name,
            kind="class",
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            docstring=docstring,
            signature=signature,
            decorators=decorators,
            complexity=methods,
            path=path or node.name,
        )
    
    def _get_decorator_name(self, node: ast.expr) -> str:
        """Extract decorator name from AST node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Call):
            return self._get_name(node.func)
        return ""
    
    def _get_name(self, node: ast.expr) -> str:
        """Extract name from AST expression."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        return ""
    
    def _get_call_name(self, node: ast.expr) -> str:
        """Extract function name from call node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # Return just the method name for simplicity
            return node.attr
        return ""

    # ---- Python tree-sitter analysis (fallback for Python 2) ----

    def _analyze_python_treesitter(self, content: str, file_path: str) -> Dict[str, Any]:
        """Analyze Python code using tree-sitter (handles Python 2 and 3)."""
        parser = self._get_ts_parser("python")
        if not parser:
            return self._analyze_generic(content, file_path, "python")

        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.warning(f"Tree-sitter parse error in {file_path}: {e}")
            return self._analyze_generic(content, file_path, "python")

        symbols = []
        imports = []
        calls = []

        def node_text(n):
            return content.encode("utf-8")[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

        def extract_docstring(body_node) -> Optional[str]:
            """Extract docstring from function/class body."""
            if not body_node:
                return None
            for child in body_node.children:
                if child.type == "expression_statement":
                    for expr in child.children:
                        if expr.type == "string":
                            text = node_text(expr)
                            # Remove quotes
                            if text.startswith('"""') or text.startswith("'''"):
                                return text[3:-3].strip()
                            elif text.startswith('"') or text.startswith("'"):
                                return text[1:-1].strip()
                    break
            return None

        def walk(node, parent_class=None, func_stack=None):
            func_stack = func_stack or []
            node_type = node.type

            # Function definitions
            if node_type == "function_definition":
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else ""
                prefix = ([parent_class] if parent_class else []) + func_stack
                func_path = ".".join(prefix + ([func_name] if func_name else []))
                parent = None
                if func_stack:
                    parent = func_stack[-1]
                elif parent_class:
                    parent = parent_class

                # Get parameters
                params_node = node.child_by_field_name("parameters")
                params = []
                if params_node:
                    for child in params_node.children:
                        if child.type == "identifier":
                            params.append(node_text(child))
                        elif child.type in ("default_parameter", "typed_parameter", "typed_default_parameter"):
                            name = child.child_by_field_name("name")
                            if name:
                                params.append(node_text(name))

                signature = f"def {func_name}({', '.join(params)})"

                # Get decorators
                decorators = []
                prev = node.prev_sibling
                while prev and prev.type == "decorator":
                    dec_text = node_text(prev).lstrip("@").split("(")[0]
                    decorators.insert(0, dec_text)
                    prev = prev.prev_sibling

                # Get docstring
                body = node.child_by_field_name("body")
                docstring = extract_docstring(body)

                symbols.append(
                    CodeSymbol(
                        name=func_name,
                        kind="method" if parent_class else "function",
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parent=parent,
                        path=func_path or func_name,
                        signature=signature,
                        decorators=decorators,
                        docstring=docstring,
                    )
                )

                # Walk function body with updated stack
                new_stack = func_stack + ([func_name] if func_name else [])
                for child in node.children:
                    walk(child, parent_class=parent_class, func_stack=new_stack)
                return

            # Class definitions
            elif node_type == "class_definition":
                name_node = node.child_by_field_name("name")
                class_name = node_text(name_node) if name_node else ""

                # Get base classes
                bases = []
                args_node = node.child_by_field_name("superclasses")
                if args_node:
                    for child in args_node.children:
                        if child.type in ("identifier", "attribute"):
                            bases.append(node_text(child))

                signature = f"class {class_name}({', '.join(bases)})" if bases else f"class {class_name}"

                # Get docstring
                body = node.child_by_field_name("body")
                docstring = extract_docstring(body)

                symbols.append(
                    CodeSymbol(
                        name=class_name,
                        kind="class",
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=signature,
                        docstring=docstring,
                        path=class_name,
                    )
                )

                # Recurse into class body
                for child in node.children:
                    walk(child, class_name, func_stack=func_stack)
                return

            # Import statements
            elif node_type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        imports.append(ImportReference(
                            module=node_text(child),
                            names=[],
                            line=node.start_point[0] + 1,
                            is_from=False,
                        ))
                    elif child.type == "aliased_import":
                        name = child.child_by_field_name("name")
                        alias = child.child_by_field_name("alias")
                        if name:
                            imports.append(ImportReference(
                                module=node_text(name),
                                names=[],
                                alias=node_text(alias) if alias else None,
                                line=node.start_point[0] + 1,
                                is_from=False,
                            ))

            # From imports
            elif node_type == "import_from_statement":
                module_node = node.child_by_field_name("module_name")
                module = node_text(module_node) if module_node else ""
                names = []
                for child in node.children:
                    if child.type in ("dotted_name", "identifier"):
                        if child != module_node:
                            names.append(node_text(child))
                    elif child.type == "aliased_import":
                        name = child.child_by_field_name("name")
                        if name:
                            names.append(node_text(name))
                imports.append(ImportReference(
                    module=module,
                    names=names,
                    line=node.start_point[0] + 1,
                    is_from=True,
                ))

            # Function calls
            elif node_type == "call":
                func = node.child_by_field_name("function")
                if func:
                    callee = ""
                    if func.type == "identifier":
                        callee = node_text(func)
                    elif func.type == "attribute":
                        attr = func.child_by_field_name("attribute")
                        if attr:
                            callee = node_text(attr)
                    if callee:
                        caller_parts = ([parent_class] if parent_class else []) + func_stack
                        caller = ".".join(caller_parts) if caller_parts else ""
                        calls.append(
                            CallReference(
                                caller=caller,
                                callee=callee,
                                line=node.start_point[0] + 1,
                                context="call",
                            )
                        )

            # Recurse
            for child in node.children:
                walk(child, parent_class, func_stack=func_stack)

        walk(root)

        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": "python",
        }

    # ---- JavaScript/TypeScript analysis (using tree-sitter) ----
    
    def _analyze_js_ts(
        self, content: str, file_path: str, language: str
    ) -> Dict[str, Any]:
        """Analyze JavaScript/TypeScript using tree-sitter."""
        ts_lang_key = language if language in _TS_LANGUAGES else "javascript"
        parser = self._get_ts_parser(ts_lang_key)
        if not parser:
            return self._empty_analysis()
        
        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.warning(f"Tree-sitter parse error in {file_path}: {e}")
            return self._empty_analysis()
        
        symbols = []
        imports = []
        calls = []

        def node_text(n):
            return content.encode("utf-8")[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

        def walk(node, parent_class=None, func_stack=None):
            func_stack = func_stack or []
            node_type = node.type

            # Classes
            if node_type == "class_declaration":
                name_node = node.child_by_field_name("name")
                class_name = node_text(name_node) if name_node else ""

                symbols.append(CodeSymbol(
                    name=class_name,
                    kind="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))

                # Walk class body
                for child in node.children:
                    walk(child, parent_class=class_name, func_stack=func_stack)
                return

            # Functions
            if node_type in ("function_declaration", "arrow_function", "function_expression"):
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                func_path = f"{parent_class}.{func_name}" if parent_class else func_name

                symbols.append(CodeSymbol(
                    name=func_name,
                    kind="function",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent=parent_class,
                    path=func_path
                ))
                # Walk body with updated stack (skip anonymous)
                if func_name and func_name != "<anonymous>":
                    for child in node.children:
                        walk(child, parent_class=parent_class, func_stack=func_stack + [func_path])
                    return

            # Methods
            if node_type == "method_definition":
                name_node = node.child_by_field_name("name")
                method_name = node_text(name_node) if name_node else ""
                method_path = f"{parent_class}.{method_name}" if parent_class else method_name

                symbols.append(CodeSymbol(
                    name=method_name,
                    kind="method",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent=parent_class,
                    path=method_path
                ))
                # Walk body with updated stack
                if method_path:
                    for child in node.children:
                        walk(child, parent_class=parent_class, func_stack=func_stack + [method_path])
                    return

            # Imports
            if node_type == "import_statement":
                source = node.child_by_field_name("source")
                if source:
                    module = node_text(source).strip('"\'')
                    imports.append(ImportReference(
                        module=module,
                        names=[],
                        line=node.start_point[0] + 1,
                        is_from=True
                    ))

            # Call expressions - now with caller context
            if node_type == "call_expression":
                func = node.child_by_field_name("function")
                if func:
                    # Extract function name from AST node types
                    callee = ""
                    if func.type == "identifier":
                        callee = node_text(func)
                    elif func.type == "member_expression":
                        prop = func.child_by_field_name("property")
                        if prop and prop.type == "property_identifier":
                            callee = node_text(prop)
                    if callee:
                        caller = func_stack[-1] if func_stack else ""
                        calls.append(CallReference(
                            caller=caller,
                            callee=callee,
                            line=node.start_point[0] + 1,
                            context="call"
                        ))

            # Recurse
            for child in node.children:
                walk(child, parent_class=parent_class, func_stack=func_stack)

        walk(root)
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": language
        }
    
    # ---- Go analysis (using tree-sitter) ----
    
    def _analyze_go(self, content: str, file_path: str) -> Dict[str, Any]:
        """Analyze Go using tree-sitter."""
        parser = self._get_ts_parser("go")
        if not parser:
            return self._analyze_generic(content, file_path, "go")
        
        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.warning(f"Tree-sitter parse error in {file_path}: {e}")
            return self._analyze_generic(content, file_path, "go")
        
        symbols = []
        imports = []
        calls = []

        def node_text(n):
            return content.encode("utf-8")[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

        def walk(node, func_stack=None):
            func_stack = func_stack or []
            node_type = node.type

            # Functions
            if node_type == "function_declaration":
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=func_name,
                    kind="function",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    path=func_name
                ))
                # Walk body with updated stack
                if func_name:
                    for child in node.children:
                        walk(child, func_stack=func_stack + [func_name])
                    return

            # Methods
            elif node_type == "method_declaration":
                name_node = node.child_by_field_name("name")
                method_name = node_text(name_node) if name_node else ""
                receiver = node.child_by_field_name("receiver")
                receiver_type = ""
                if receiver:
                    for child in receiver.children:
                        if child.type == "type_identifier":
                            receiver_type = node_text(child)
                            break
                func_path = f"{receiver_type}.{method_name}" if receiver_type else method_name
                symbols.append(CodeSymbol(
                    name=method_name,
                    kind="method",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent=receiver_type,
                    path=func_path
                ))
                # Walk body with updated stack
                if func_path:
                    for child in node.children:
                        walk(child, func_stack=func_stack + [func_path])
                    return

            # Types (struct, interface)
            elif node_type == "type_declaration":
                for child in node.children:
                    if child.type == "type_spec":
                        name_node = child.child_by_field_name("name")
                        type_name = node_text(name_node) if name_node else ""
                        type_node = child.child_by_field_name("type")
                        kind = "struct"
                        if type_node and type_node.type == "interface_type":
                            kind = "interface"
                        symbols.append(CodeSymbol(
                            name=type_name,
                            kind=kind,
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1
                        ))

            # Imports
            elif node_type == "import_declaration":
                for child in node.children:
                    if child.type == "import_spec":
                        path_node = child.child_by_field_name("path")
                        if path_node:
                            module = node_text(path_node).strip('"')
                            imports.append(ImportReference(
                                module=module,
                                names=[],
                                line=child.start_point[0] + 1,
                                is_from=True
                            ))
                    elif child.type == "import_spec_list":
                        for spec in child.children:
                            if spec.type == "import_spec":
                                path_node = spec.child_by_field_name("path")
                                if path_node:
                                    module = node_text(path_node).strip('"')
                                    imports.append(ImportReference(
                                        module=module,
                                        names=[],
                                        line=spec.start_point[0] + 1,
                                        is_from=True
                                    ))

            # Calls - now with caller context
            elif node_type == "call_expression":
                func = node.child_by_field_name("function")
                if func:
                    name = node_text(func)
                    base = name.split(".")[-1] if "." in name else name
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", base):
                        caller = ".".join(func_stack) if func_stack else ""
                        calls.append(CallReference(
                            caller=caller,
                            callee=base,
                            line=node.start_point[0] + 1,
                            context="call"
                        ))

            for child in node.children:
                walk(child, func_stack=func_stack)

        walk(root)
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": "go"
        }
    
    # ---- Rust analysis (using tree-sitter) ----
    
    def _analyze_rust(self, content: str, file_path: str) -> Dict[str, Any]:
        """Analyze Rust using tree-sitter."""
        parser = self._get_ts_parser("rust")
        if not parser:
            return self._analyze_generic(content, file_path, "rust")
        
        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.warning(f"Tree-sitter parse error in {file_path}: {e}")
            return self._analyze_generic(content, file_path, "rust")
        
        symbols = []
        imports = []
        calls = []

        def node_text(n):
            return content.encode("utf-8")[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

        def walk(node, parent_struct=None, func_stack=None):
            func_stack = func_stack or []
            node_type = node.type

            # Functions
            if node_type == "function_item":
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else ""
                func_path = f"{parent_struct}.{func_name}" if parent_struct else func_name
                symbols.append(CodeSymbol(
                    name=func_name,
                    kind="function",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent=parent_struct,
                    path=func_path
                ))
                # Walk body with updated stack
                if func_path:
                    for child in node.children:
                        walk(child, parent_struct=parent_struct, func_stack=func_stack + [func_path])
                    return

            # Structs
            elif node_type == "struct_item":
                name_node = node.child_by_field_name("name")
                struct_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=struct_name,
                    kind="struct",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))

            # Enums
            elif node_type == "enum_item":
                name_node = node.child_by_field_name("name")
                enum_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=enum_name,
                    kind="enum",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))

            # Traits
            elif node_type == "trait_item":
                name_node = node.child_by_field_name("name")
                trait_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=trait_name,
                    kind="trait",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))

            # Impl blocks
            elif node_type == "impl_item":
                type_node = node.child_by_field_name("type")
                impl_type = node_text(type_node).split("<")[0].strip() if type_node else ""
                for child in node.children:
                    walk(child, parent_struct=impl_type, func_stack=func_stack)
                return

            # Use statements
            elif node_type == "use_declaration":
                arg = node.child_by_field_name("argument")
                if arg:
                    imports.append(ImportReference(
                        module=node_text(arg).strip(),
                        names=[],
                        line=node.start_point[0] + 1,
                        is_from=True
                    ))

            # Calls and macros - now with caller context
            elif node_type in ("call_expression", "macro_invocation"):
                func = node.child_by_field_name("function") or node.child_by_field_name("macro")
                if func:
                    name = node_text(func)
                    base = name.split("::")[-1].rstrip("!") if "::" in name else name.rstrip("!")
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", base):
                        caller = func_stack[-1] if func_stack else ""
                        calls.append(CallReference(
                            caller=caller,
                            callee=base,
                            line=node.start_point[0] + 1,
                            context="call"
                        ))

            for child in node.children:
                walk(child, parent_struct=parent_struct, func_stack=func_stack)

        walk(root)
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": "rust"
        }
    
    # ---- Java analysis (using tree-sitter) ----
    
    def _analyze_java(self, content: str, file_path: str) -> Dict[str, Any]:
        """Analyze Java using tree-sitter."""
        parser = self._get_ts_parser("java")
        if not parser:
            return self._analyze_generic(content, file_path, "java")
        
        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.warning(f"Tree-sitter parse error in {file_path}: {e}")
            return self._analyze_generic(content, file_path, "java")
        
        symbols = []
        imports = []
        calls = []

        def node_text(n):
            return content.encode("utf-8")[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

        def walk(node, parent_class=None, func_stack=None):
            func_stack = func_stack or []
            node_type = node.type

            # Classes
            if node_type == "class_declaration":
                name_node = node.child_by_field_name("name")
                class_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=class_name,
                    kind="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))
                for child in node.children:
                    walk(child, parent_class=class_name, func_stack=func_stack)
                return

            # Interfaces
            elif node_type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                iface_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=iface_name,
                    kind="interface",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))
                for child in node.children:
                    walk(child, parent_class=iface_name, func_stack=func_stack)
                return

            # Methods
            elif node_type == "method_declaration":
                name_node = node.child_by_field_name("name")
                method_name = node_text(name_node) if name_node else ""
                method_path = f"{parent_class}.{method_name}" if parent_class else method_name
                symbols.append(CodeSymbol(
                    name=method_name,
                    kind="method",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent=parent_class,
                    path=method_path
                ))
                # Walk body with updated stack
                if method_path:
                    for child in node.children:
                        walk(child, parent_class=parent_class, func_stack=func_stack + [method_path])
                    return

            # Constructors
            elif node_type == "constructor_declaration":
                name_node = node.child_by_field_name("name")
                ctor_name = node_text(name_node) if name_node else ""
                ctor_path = f"{parent_class}.{ctor_name}" if parent_class else ctor_name
                symbols.append(CodeSymbol(
                    name=ctor_name,
                    kind="constructor",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent=parent_class,
                    path=ctor_path
                ))
                # Walk body with updated stack
                if ctor_path:
                    for child in node.children:
                        walk(child, parent_class=parent_class, func_stack=func_stack + [ctor_path])
                    return

            # Imports
            elif node_type == "import_declaration":
                for child in node.children:
                    if child.type == "scoped_identifier" or child.type == "identifier":
                        imports.append(ImportReference(
                            module=node_text(child),
                            names=[],
                            line=node.start_point[0] + 1,
                            is_from=True
                        ))
                        break

            # Method calls - now with caller context
            elif node_type == "method_invocation":
                name_node = node.child_by_field_name("name")
                if name_node:
                    caller = func_stack[-1] if func_stack else ""
                    calls.append(CallReference(
                        caller=caller,
                        callee=node_text(name_node),
                        line=node.start_point[0] + 1,
                        context="call"
                    ))

            for child in node.children:
                walk(child, parent_class=parent_class, func_stack=func_stack)

        walk(root)
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": "java"
        }
    
    # ---- C/C++ analysis (using tree-sitter) ----
    
    def _analyze_c_cpp(self, content: str, file_path: str, language: str) -> Dict[str, Any]:
        """Analyze C/C++ using tree-sitter."""
        parser = self._get_ts_parser(language)
        if not parser:
            return self._analyze_generic(content, file_path, language)
        
        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.warning(f"Tree-sitter parse error in {file_path}: {e}")
            return self._analyze_generic(content, file_path, language)
        
        symbols = []
        imports = []
        calls = []

        def node_text(n):
            return content.encode("utf-8")[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

        def walk(node, parent_class=None, func_stack=None):
            func_stack = func_stack or []
            node_type = node.type

            # Functions
            if node_type == "function_definition":
                decl = node.child_by_field_name("declarator")
                func_name = ""
                if decl:
                    for child in decl.children:
                        if child.type == "identifier":
                            func_name = node_text(child)
                            break
                        elif child.type == "function_declarator":
                            for subchild in child.children:
                                if subchild.type == "identifier":
                                    func_name = node_text(subchild)
                                    break
                if func_name:
                    func_path = f"{parent_class}::{func_name}" if parent_class else func_name
                    symbols.append(CodeSymbol(
                        name=func_name,
                        kind="function",
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parent=parent_class,
                        path=func_path
                    ))
                    # Walk body with updated stack
                    for child in node.children:
                        walk(child, parent_class=parent_class, func_stack=func_stack + [func_path])
                    return

            # Classes (C++)
            elif node_type == "class_specifier":
                name_node = node.child_by_field_name("name")
                class_name = node_text(name_node) if name_node else ""
                if class_name:
                    symbols.append(CodeSymbol(
                        name=class_name,
                        kind="class",
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1
                    ))
                    for child in node.children:
                        walk(child, parent_class=class_name, func_stack=func_stack)
                    return

            # Structs
            elif node_type == "struct_specifier":
                name_node = node.child_by_field_name("name")
                struct_name = node_text(name_node) if name_node else ""
                if struct_name:
                    symbols.append(CodeSymbol(
                        name=struct_name,
                        kind="struct",
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1
                    ))

            # Includes
            elif node_type == "preproc_include":
                path_node = node.child_by_field_name("path")
                if path_node:
                    path = node_text(path_node).strip('<">').strip()
                    imports.append(ImportReference(
                        module=path,
                        names=[],
                        line=node.start_point[0] + 1,
                        is_from=False
                    ))

            # Calls - now with caller context
            elif node_type == "call_expression":
                func = node.child_by_field_name("function")
                if func:
                    # Extract callee from AST - handle identifier or qualified_identifier
                    callee = ""
                    if func.type == "identifier":
                        callee = node_text(func)
                    elif func.type == "qualified_identifier":
                        # Get last component: std::vector -> vector
                        callee = node_text(func).split("::")[-1]
                    elif func.type == "field_expression":
                        # obj.method() -> method
                        field = func.child_by_field_name("field")
                        if field and field.type == "field_identifier":
                            callee = node_text(field)
                    if callee:
                        caller = func_stack[-1] if func_stack else ""
                        calls.append(CallReference(
                            caller=caller,
                            callee=callee,
                            line=node.start_point[0] + 1,
                            context="call"
                        ))

            for child in node.children:
                walk(child, parent_class=parent_class, func_stack=func_stack)

        walk(root)
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": language
        }
    
    # ---- Ruby analysis (using tree-sitter) ----
    
    def _analyze_ruby(self, content: str, file_path: str) -> Dict[str, Any]:
        """Analyze Ruby using tree-sitter."""
        parser = self._get_ts_parser("ruby")
        if not parser:
            return self._analyze_generic(content, file_path, "ruby")
        
        try:
            tree = parser.parse(content.encode("utf-8"))
            root = tree.root_node
        except Exception as e:
            logger.warning(f"Tree-sitter parse error in {file_path}: {e}")
            return self._analyze_generic(content, file_path, "ruby")
        
        symbols = []
        imports = []
        calls = []

        def node_text(n):
            return content.encode("utf-8")[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

        def walk(node, parent_class=None, func_stack=None):
            func_stack = func_stack or []
            node_type = node.type

            # Classes
            if node_type == "class":
                name_node = node.child_by_field_name("name")
                class_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=class_name,
                    kind="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))
                for child in node.children:
                    walk(child, parent_class=class_name, func_stack=func_stack)
                return

            # Modules
            elif node_type == "module":
                name_node = node.child_by_field_name("name")
                module_name = node_text(name_node) if name_node else ""
                symbols.append(CodeSymbol(
                    name=module_name,
                    kind="module",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1
                ))
                for child in node.children:
                    walk(child, parent_class=module_name, func_stack=func_stack)
                return

            # Methods
            elif node_type == "method":
                name_node = node.child_by_field_name("name")
                method_name = node_text(name_node) if name_node else ""
                method_path = f"{parent_class}.{method_name}" if parent_class else method_name
                symbols.append(CodeSymbol(
                    name=method_name,
                    kind="method",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent=parent_class,
                    path=method_path
                ))
                # Walk body with updated stack
                if method_path:
                    for child in node.children:
                        walk(child, parent_class=parent_class, func_stack=func_stack + [method_path])
                    return

            # Require statements
            elif node_type == "call":
                method = node.child_by_field_name("method")
                if method:
                    method_name = node_text(method)
                    if method_name in ("require", "require_relative", "load"):
                        args = node.child_by_field_name("arguments")
                        if args:
                            for arg in args.children:
                                if arg.type == "string":
                                    path = node_text(arg).strip("'\"")
                                    imports.append(ImportReference(
                                        module=path,
                                        names=[],
                                        line=node.start_point[0] + 1,
                                        is_from=True
                                    ))
                                    break
                    else:
                        # Regular method call - now with caller context
                        caller = func_stack[-1] if func_stack else ""
                        calls.append(CallReference(
                            caller=caller,
                            callee=method_name,
                            line=node.start_point[0] + 1,
                            context="call"
                        ))

            # Method calls (method_call node type) - now with caller context
            elif node_type == "method_call":
                method = node.child_by_field_name("method")
                if method:
                    caller = func_stack[-1] if func_stack else ""
                    calls.append(CallReference(
                        caller=caller,
                        callee=node_text(method),
                        line=node.start_point[0] + 1,
                        context="call"
                    ))

            for child in node.children:
                walk(child, parent_class=parent_class, func_stack=func_stack)

        walk(root)
        
        return {
            "symbols": symbols,
            "imports": imports,
            "calls": calls,
            "language": "ruby"
        }
    
    def _get_ts_parser(self, language: str):
        """Get or create tree-sitter parser for language.

        Uses tree-sitter 0.25+ API with pre-loaded Language objects.
        """
        if language in self._parsers:
            return self._parsers[language]

        if not _TS_AVAILABLE or language not in _TS_LANGUAGES:
            return None

        try:
            lang = _TS_LANGUAGES[language]
            # Support both APIs:
            # - tree_sitter<0.25 (or some builds): Parser(lang)
            # - tree_sitter>=0.25: Parser(); parser.set_language(lang)
            parser = None
            try:
                p = Parser()  # type: ignore[call-arg]
                if hasattr(p, "set_language"):
                    p.set_language(lang)  # type: ignore[attr-defined]
                    parser = p
                else:
                    try:
                        setattr(p, "language", lang)
                        parser = p
                    except Exception:
                        parser = None
            except Exception:
                parser = None
            if parser is None:
                parser = Parser(lang)  # type: ignore[misc]
            self._parsers[language] = parser
            return parser
        except Exception as e:
            logger.warning(f"Failed to create tree-sitter parser for {language}: {e}")
            return None
    
    # ---- Generic/fallback analysis ----
    
    def _analyze_generic(
        self, content: str, file_path: str, language: str
    ) -> Dict[str, Any]:
        """Fallback regex-based analysis for unsupported languages."""
        symbols = []
        lines = content.splitlines()
        
        # Very basic heuristics
        for i, line in enumerate(lines, 1):
            # Try to find function-like patterns
            if re.match(r'^\s*(def|function|func|fn)\s+(\w+)', line):
                match = re.match(r'^\s*(?:def|function|func|fn)\s+(\w+)', line)
                if match:
                    symbols.append(CodeSymbol(
                        name=match.group(1),
                        kind="function",
                        start_line=i,
                        end_line=i  # Can't determine without parsing
                    ))
            
            # Try to find class-like patterns
            if re.match(r'^\s*class\s+(\w+)', line):
                match = re.match(r'^\s*class\s+(\w+)', line)
                if match:
                    symbols.append(CodeSymbol(
                        name=match.group(1),
                        kind="class",
                        start_line=i,
                        end_line=i
                    ))
        
        return {
            "symbols": symbols,
            "imports": [],
            "calls": [],
            "language": language
        }
    
    # ---- Helper methods ----
    
    def _empty_analysis(self) -> Dict[str, Any]:
        """Return empty analysis result."""
        return {
            "symbols": [],
            "imports": [],
            "calls": [],
            "language": "unknown"
        }
    
    def _chunk_lines_simple(
        self, content: str, max_lines: int, overlap: int
    ) -> List[CodeContext]:
        """Simple line-based chunking fallback."""
        lines = content.splitlines()
        chunks = []
        
        i = 0
        while i < len(lines):
            chunk_end = min(i + max_lines, len(lines))
            chunk_lines = lines[i:chunk_end]
            
            chunks.append(CodeContext(
                chunk_text="\n".join(chunk_lines),
                start_line=i + 1,
                end_line=chunk_end,
                symbols=[],
                imports=[],
                calls=[],
                dependencies=set(),
                is_semantic_unit=False
            ))
            
            i = chunk_end - overlap if chunk_end < len(lines) else chunk_end
        
        return chunks
    
    def _fill_gaps(
        self,
        chunks: List[CodeContext],
        lines: List[str],
        max_lines: int,
        overlap: int,
        analysis: Dict[str, Any]
    ):
        """Fill gaps between symbol chunks with module-level code."""
        if not chunks:
            return
        
        # Find uncovered regions
        covered = set()
        for chunk in chunks:
            covered.update(range(chunk.start_line, chunk.end_line + 1))
        
        gaps = []
        gap_start = None
        for i in range(1, len(lines) + 1):
            if i not in covered:
                if gap_start is None:
                    gap_start = i
            else:
                if gap_start is not None:
                    gaps.append((gap_start, i - 1))
                    gap_start = None
        
        if gap_start is not None:
            gaps.append((gap_start, len(lines)))
        
        # Create chunks for gaps
        for start, end in gaps:
            if end - start + 1 < 3:  # Skip tiny gaps
                continue
            
            gap_lines = lines[start - 1:end]
            chunks.append(CodeContext(
                chunk_text="\n".join(gap_lines),
                start_line=start,
                end_line=end,
                symbols=[],
                imports=[imp for imp in analysis.get("imports", []) if start <= imp.line <= end],
                calls=[],
                dependencies=set(),
                is_semantic_unit=False
            ))
        
        # Re-sort chunks by start line
        chunks.sort(key=lambda c: c.start_line)
    
    def _extract_dependencies(
        self, imports: List[ImportReference], calls: List[CallReference]
    ) -> Set[str]:
        """Extract unique dependencies from imports and calls."""
        deps = set()
        
        for imp in imports:
            deps.add(imp.module)
            deps.update(imp.names)
        
        for call in calls:
            deps.add(call.callee)
        
        return deps


# Global analyzer instance
_analyzer: Optional[ASTAnalyzer] = None


def get_ast_analyzer(reset: bool = False) -> ASTAnalyzer:
    """Get or create global AST analyzer instance."""
    global _analyzer

    if _analyzer is None or reset:
        use_ts = os.environ.get("USE_TREE_SITTER", "1").lower() in {"1", "true", "yes", "on"}
        _analyzer = ASTAnalyzer(use_tree_sitter=use_ts)

    return _analyzer


# ---------------------------------------------------------------------------
# Language-Aware Builtin Detection
# ---------------------------------------------------------------------------
# Builtins are detected using tree-sitter's query system directly.
# This is the most scalable approach - we parse code and check if nodes
# get @*.builtin captures. Works uniformly for ALL languages.

# Cache for query objects and parsers per language
_TS_QUERY_CACHE: Dict[str, Tuple[Any, Any, Any]] = {}  # lang -> (parser, query, lang_obj)


def _get_ts_query_for_language(language: str) -> Optional[Tuple[Any, Any, Any]]:
    """Get tree-sitter parser and highlights query for a language.

    Returns (parser, query, lang_obj) tuple or None if unavailable.
    """
    if not _TS_AVAILABLE:
        return None

    lang = language.lower().strip()

    # Normalize aliases
    if lang in ("js", "jsx"):
        lang = "javascript"
    elif lang in ("ts", "tsx"):
        lang = "typescript"
    elif lang in ("c++", "cxx", "cc"):
        lang = "cpp"
    elif lang in ("c#", "cs"):
        lang = "csharp"

    # Check cache
    if lang in _TS_QUERY_CACHE:
        return _TS_QUERY_CACHE[lang]

    # Get language object from already-loaded _TS_LANGUAGES
    if lang not in _TS_LANGUAGES:
        _TS_QUERY_CACHE[lang] = None
        return None

    lang_obj = _TS_LANGUAGES[lang]

    # Find the module and its highlights.scm
    lang_to_module = {
        "python": "tree_sitter_python",
        "javascript": "tree_sitter_javascript",
        "typescript": "tree_sitter_typescript",
        "go": "tree_sitter_go",
        "rust": "tree_sitter_rust",
        "java": "tree_sitter_java",
        "c": "tree_sitter_c",
        "cpp": "tree_sitter_cpp",
        "ruby": "tree_sitter_ruby",
        "c_sharp": "tree_sitter_c_sharp",
        "csharp": "tree_sitter_c_sharp",
        "bash": "tree_sitter_bash",
        "shell": "tree_sitter_bash",
        "sh": "tree_sitter_bash",
        "json": "tree_sitter_json",
        "yaml": "tree_sitter_yaml",
        "html": "tree_sitter_html",
        "css": "tree_sitter_css",
        "markdown": "tree_sitter_markdown",
    }

    module_name = lang_to_module.get(lang)
    if not module_name:
        _TS_QUERY_CACHE[lang] = None
        return None

    try:
        import importlib
        from tree_sitter import Query, QueryCursor

        lang_module = importlib.import_module(module_name)
        mod_path = os.path.dirname(lang_module.__file__)
        highlights_path = os.path.join(mod_path, 'queries', 'highlights.scm')

        if not os.path.exists(highlights_path):
            _TS_QUERY_CACHE[lang] = None
            return None

        with open(highlights_path) as f:
            query_text = f.read()

        parser = Parser(lang_obj)
        query = Query(lang_obj, query_text)

        result = (parser, query, lang_obj)
        _TS_QUERY_CACHE[lang] = result
        return result
    except Exception as e:
        logger.debug(f"Failed to load tree-sitter query for {lang}: {e}")
        _TS_QUERY_CACHE[lang] = None
        return None


# Cache for parsers without queries
_TS_PARSER_CACHE: Dict[str, Optional["Parser"]] = {}


def _get_parser_for_language(lang: str) -> Optional["Parser"]:
    """Get just a parser for a language (for tree-walking without queries)."""
    if lang in _TS_PARSER_CACHE:
        return _TS_PARSER_CACHE[lang]

    try:
        from tree_sitter import Parser, Language

        # Map language to module
        lang_modules = {
            "python": "tree_sitter_python",
            "javascript": "tree_sitter_javascript",
            "typescript": "tree_sitter_typescript",
            "go": "tree_sitter_go",
            "rust": "tree_sitter_rust",
            "java": "tree_sitter_java",
            "c": "tree_sitter_c",
            "cpp": "tree_sitter_cpp",
            "ruby": "tree_sitter_ruby",
            "csharp": "tree_sitter_c_sharp",
            "c_sharp": "tree_sitter_c_sharp",
            "bash": "tree_sitter_bash",
        }

        mod_name = lang_modules.get(lang)
        if not mod_name:
            _TS_PARSER_CACHE[lang] = None
            return None

        mod = importlib.import_module(mod_name)

        # Get language object
        if lang in ("typescript",):
            lang_obj = Language(mod.language_typescript())
        elif lang in ("csharp", "c_sharp"):
            lang_func = getattr(mod, "language_c_sharp", None) or getattr(mod, "language", None)
            if lang_func:
                lang_obj = Language(lang_func())
            else:
                _TS_PARSER_CACHE[lang] = None
                return None
        else:
            lang_obj = Language(mod.language())

        parser = Parser(lang_obj)
        _TS_PARSER_CACHE[lang] = parser
        return parser
    except Exception as e:
        logger.debug(f"Failed to load parser for {lang}: {e}")
        _TS_PARSER_CACHE[lang] = None
        return None


def is_builtin_via_query(name: str, language: str) -> bool:
    """Check if a symbol is a builtin using tree-sitter's query system.

    This is the scalable approach - we create a minimal code snippet,
    parse it, and check if the identifier gets a @*.builtin capture.
    Works for ALL languages uniformly.
    """
    # Normalize language name
    lang = language.lower().strip()
    if lang in ("js", "jsx"):
        lang = "javascript"
    elif lang in ("ts", "tsx"):
        lang = "typescript"
    elif lang in ("c++", "cxx", "cc"):
        lang = "cpp"
    elif lang in ("c#", "cs"):
        lang = "csharp"
    elif lang == "c_sharp":
        lang = "csharp"

    # Try to get query-based detection (preferred)
    ts_info = _get_ts_query_for_language(language)
    parser = None
    query = None
    if ts_info is not None:
        parser, query, _ = ts_info
    else:
        # Fallback: load just the parser without query for tree-walking
        parser = _get_parser_for_language(lang)

    # Generate minimal code snippets containing the identifier in multiple contexts
    # We try multiple syntactic positions to catch builtins used as functions, types, etc.
    if lang in ("python",):
        # Python: builtins as function calls
        code = f"{name}()".encode()
    elif lang in ("javascript", "jsx"):
        # JavaScript: builtins can be objects (console, document, window) or constructors
        code = f"{name}; {name}()".encode()
    elif lang in ("typescript", "tsx"):
        # TypeScript: predefined_type captures for string, number, boolean, etc.
        # Also try as regular identifier
        code = f"let x: {name}; {name}()".encode()
    elif lang == "go":
        code = f"package main\nfunc f() {{ {name}() }}".encode()
    elif lang == "rust":
        # Rust: check both function calls and types
        code = f"fn f() {{ let _: {name} = {name}(); }}".encode()
    elif lang == "java":
        # Java: primitive types in declaration, also as method call
        code = f"class X {{ {name} x; void f() {{ {name}(); }} }}".encode()
    elif lang in ("c", "cpp"):
        # C/C++: primitive types in declarations
        code = f"{name} x; void f() {{ {name}(); }}".encode()
    elif lang == "csharp":
        # C#: primitive types and method calls
        code = f"class X {{ {name} x; void f() {{ {name}(); }} }}".encode()
    elif lang == "ruby":
        # Ruby: method calls and keywords
        code = f"{name}; {name}()".encode()
    elif lang in ("bash", "shell", "sh"):
        # Bash: command names
        code = f"{name}".encode()
    else:
        code = f"{name}()".encode()

    # Node types that indicate language primitives/builtins at the grammar level
    builtin_node_types = frozenset({
        'primitive_type',           # C, C++, Java: int, char, void, float, double
        'predefined_type',          # TypeScript: string, number, boolean
        'sized_type_specifier',     # C: short, long, unsigned
        'auto',                     # C++: auto keyword
        'nullptr',                  # C++: nullptr literal
        'null',                     # C++/Java: null literal
        'placeholder_type_specifier',  # C++: auto/decltype
        'true', 'false',            # Boolean literals
        'nil',                      # Ruby/Go: nil literal
        'self',                     # Rust/Python/Ruby: self reference
    })

    if parser is None:
        return False

    try:
        tree = parser.parse(code)

        # Strategy 1: Walk tree directly for builtin node types
        # This works even if highlights.scm doesn't capture them (like C++, C#)
        def find_builtin_node(node):
            if node.type in builtin_node_types:
                node_text = code[node.start_byte:node.end_byte].decode()
                if node_text == name:
                    return True
            for child in node.children:
                if find_builtin_node(child):
                    return True
            return False

        if find_builtin_node(tree.root_node):
            return True

        # Strategy 2: Check query captures for @*.builtin (if query available)
        if query is not None:
            from tree_sitter import QueryCursor
            cursor = QueryCursor(query)
            for _, captures_dict in cursor.matches(tree.root_node):
                for capture_name, nodes in captures_dict.items():
                    if 'builtin' not in capture_name:
                        continue
                    for node in nodes:
                        node_text = code[node.start_byte:node.end_byte].decode()
                        if node_text == name:
                            return True
        return False
    except Exception as e:
        logger.debug(f"Query failed for {name} in {language}: {e}")
        return False


def is_builtin(name: str, language: str) -> bool:
    """Check if a symbol name is a builtin for the given language.

    Uses tree-sitter's query system to check if the symbol gets a @*.builtin
    capture. This works uniformly for ALL languages.

    Args:
        name: Symbol name (may be qualified like "os.path.join")
        language: Programming language (e.g., "python", "javascript")

    Returns:
        True if the symbol is a language builtin
    """
    # Check base name (handles qualified names like "os.path.join" -> "join")
    base_name = name.split(".")[-1] if "." in name else name
    base_name = base_name.split("::")[-1] if "::" in base_name else base_name

    return is_builtin_via_query(base_name, language)


def is_stdlib(module: str, language: str) -> bool:
    """Check if a module is part of the language's standard library.

    NOTE: No hardcoded stdlib lists - we rely on symbol resolution.
    If a module can't be resolved in the codebase, it's treated as external.
    This function exists for API compatibility but always returns False.

    Args:
        module: Module name (may be qualified like "os.path")
        language: Programming language

    Returns:
        Always False - stdlib detection removed in favor of tree-sitter queries
    """
    # No hardcoded stdlib lists - unresolved imports are <external>
    return False


def categorize_symbol(name: str, language: str) -> str:
    """Categorize a symbol as builtin or external.

    Uses tree-sitter query system for builtin detection.
    Everything else is external (resolved by symbol resolver at graph time).

    Args:
        name: Symbol or module name
        language: Programming language

    Returns:
        Category string: "<builtin>" or "<external>"
    """
    if is_builtin(name, language):
        return "<builtin>"
    return "<external>"


# Convenience functions
def extract_symbols(file_path: str, language: str) -> List[CodeSymbol]:
    """Extract symbols from a file."""
    analyzer = get_ast_analyzer()
    return analyzer.extract_symbols_with_context(file_path, language)


def chunk_code_semantically(
    content: str,
    language: str,
    max_lines: int = 120,
    overlap: int = 20
) -> List[Dict[str, Any]]:
    """
    Chunk code semantically, returning simplified dicts for indexing.

    Returns list of dicts compatible with existing chunking interface.
    Now includes chunk-specific calls and imports for accurate callees queries.
    """
    analyzer = get_ast_analyzer()
    contexts = analyzer.chunk_semantic(content, language, max_lines, overlap)

    # Convert to simple dict format, preserving calls/imports for graph edges
    return [
        {
            "text": ctx.chunk_text,
            "start": ctx.start_line,
            "end": ctx.end_line,
            "is_semantic": ctx.is_semantic_unit,
            "symbols": [s.name for s in ctx.symbols],
            "symbol_types": [s.kind for s in ctx.symbols],
            # Chunk-specific calls and imports (filtered by line range in analyzer)
            "calls": [c.callee for c in ctx.calls],
            "imports": [i.module for i in ctx.imports],
        }
        for ctx in contexts
    ]


if __name__ == "__main__":
    # Example usage
    import json
    
    logging.basicConfig(level=logging.INFO)
    
    test_code = '''
import os
from typing import List, Dict

class DataProcessor:
    """Process data efficiently."""
    
    def __init__(self, config: Dict):
        self.config = config
    
    def process(self, data: List[str]) -> List[str]:
        """Process the input data."""
        results = []
        for item in data:
            if item:
                results.append(self.transform(item))
        return results
    
    def transform(self, item: str) -> str:
        """Transform a single item."""
        return item.upper()

def main():
    """Main entry point."""
    processor = DataProcessor({})
    result = processor.process(["hello", "world"])
    print(result)

if __name__ == "__main__":
    main()
'''
    
    analyzer = get_ast_analyzer()
    
    print("=== Symbol Extraction ===")
    analysis = analyzer.analyze_file("test.py", "python", test_code)
    for symbol in analysis["symbols"]:
        print(f"{symbol.kind}: {symbol.name} (lines {symbol.start_line}-{symbol.end_line})")
        if symbol.docstring:
            print(f"  Docstring: {symbol.docstring[:50]}...")
    
    print("\n=== Imports ===")
    for imp in analysis["imports"]:
        print(f"Line {imp.line}: {imp.module} -> {imp.names}")
    
    print("\n=== Semantic Chunking ===")
    chunks = chunk_code_semantically(test_code, "python", max_lines=20)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i+1} (lines {chunk['start']}-{chunk['end']}):")
        print(f"  Symbols: {chunk['symbols']}")
        print(f"  Semantic unit: {chunk['is_semantic']}")
        print()
