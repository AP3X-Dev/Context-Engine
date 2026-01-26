#!/usr/bin/env python3
"""
ingest/metadata.py - Metadata extraction for indexed files.

This module provides functions for extracting git metadata, imports, calls,
and other file-level information for the indexing pipeline.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict



logger = logging.getLogger(__name__)
def _git_metadata(file_path: Path) -> Tuple[int, int, int]:
    """Return (last_modified_at, churn_count, author_count) using git when available.
    
    Falls back to fs mtime and zeros when not in a repo.
    """
    try:
        import subprocess

        fp = str(file_path)
        # last commit unix timestamp (%ct)
        ts = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", fp],
            capture_output=True,
            text=True,
            cwd=file_path.parent,
        ).stdout.strip()
        last_ts = int(ts) if ts.isdigit() else int(file_path.stat().st_mtime)
        # churn: number of commits touching this file (bounded)
        churn_s = subprocess.run(
            ["git", "rev-list", "--count", "HEAD", "--", fp],
            capture_output=True,
            text=True,
            cwd=file_path.parent,
        ).stdout.strip()
        churn = int(churn_s) if churn_s.isdigit() else 0
        # author count
        authors = subprocess.run(
            ["git", "shortlog", "-s", "--", fp],
            capture_output=True,
            text=True,
            cwd=file_path.parent,
        ).stdout
        author_count = len([ln for ln in authors.splitlines() if ln.strip()])
        return last_ts, churn, author_count
    except Exception:
        try:
            return int(file_path.stat().st_mtime), 0, 0
        except Exception:
            return int(time.time()), 0, 0


def _extract_imports(language: str, text: str) -> List[str]:
    """Lightweight import extraction per language (best-effort)."""
    lines = text.splitlines()
    imps: List[str] = []
    if language == "python":
        for ln in lines:
            m = re.match(r"^\s*import\s+([\w\.]+)", ln)
            if m:
                imps.append(m.group(1))
                continue
            m = re.match(r"^\s*from\s+([\w\.]+)\s+import\s+", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language in ("javascript", "typescript"):
        for ln in lines:
            m = re.match(r"^\s*import\s+.*?from\s+['\"]([^'\"]+)['\"]", ln)
            if m:
                imps.append(m.group(1))
                continue
            # Match require statements: require('x'), const x = require('x'), etc.
            m = re.search(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "go":
        block = False
        for ln in lines:
            if re.match(r"^\s*import\s*\(", ln):
                block = True
                continue
            if block:
                if ")" in ln:
                    block = False
                    continue
                m = re.match(r"^\s*\"([^\"]+)\"", ln)
                if m:
                    imps.append(m.group(1))
                    continue
            m = re.match(r"^\s*import\s+\"([^\"]+)\"", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "java":
        for ln in lines:
            m = re.match(r"^\s*import\s+([\w\.\*]+);", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "csharp":
        for ln in lines:
            # Match: using System; using static System.Math; using Alias = System.Text;
            m = re.match(r"^\s*using\s+(?:static\s+)?([A-Za-z_][\w\._]*)\s*;", ln)
            if m:
                imps.append(m.group(1))
                continue
            # Match alias: using Alias = Namespace.Type;
            m = re.match(r"^\s*using\s+\w+\s*=\s*([A-Za-z_][\w\._]*)\s*;", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "php":
        for ln in lines:
            m = re.match(r"^\s*use\s+(?:function\s+|const\s+)?([A-Za-z_][A-Za-z0-9_\\\\]*)\s*;", ln)
            if m:
                imps.append(m.group(1).replace("\\\\", "\\"))
                continue
        for ln in lines:
            m = re.match(r"^\s*(?:include|include_once|require|require_once)\s*\(?\s*['\"]([^'\"]+)['\"]\s*\)?\s*;", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "rust":
        for ln in lines:
            m = re.match(r"^\s*use\s+([^;]+);", ln)
            if m:
                imps.append(m.group(1).strip())
                continue
    elif language in ("c", "cpp"):
        for ln in lines:
            m = re.match(r'^\s*#include\s*[<"]([^>"]+)[>"]', ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "ruby":
        for ln in lines:
            m = re.match(r"^\s*require\s+['\"]([^'\"]+)['\"]", ln)
            if m:
                imps.append(m.group(1))
                continue
            m = re.match(r"^\s*require_relative\s+['\"]([^'\"]+)['\"]", ln)
            if m:
                imps.append(m.group(1))
                continue
            m = re.match(r"^\s*load\s+['\"]([^'\"]+)['\"]", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "kotlin":
        for ln in lines:
            m = re.match(r"^\s*import\s+([\w\.\*]+)", ln)
            if m:
                full_path = m.group(1)
                imps.append(full_path)
                # Also add leaf symbol (class/function name)
                if "." in full_path and not full_path.endswith("*"):
                    leaf = full_path.rsplit(".", 1)[-1]
                    if leaf and leaf not in imps:
                        imps.append(leaf)
                continue
    elif language == "swift":
        for ln in lines:
            m = re.match(r"^\s*import\s+(\w+)", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "scala":
        for ln in lines:
            m = re.match(r"^\s*import\s+([\w\.\{\}\,\s_]+)", ln)
            if m:
                full_path = m.group(1).strip()
                imps.append(full_path)
                # Also add leaf symbol (class/function name)
                if "." in full_path and not full_path.endswith("_"):
                    leaf = full_path.rsplit(".", 1)[-1]
                    if leaf and leaf not in imps and not any(c in leaf for c in "{},"):
                        imps.append(leaf)
                continue
    elif language == "terraform":
        for ln in lines:
            m = re.match(r"^\s*source\s*=\s*['\"]([^'\"]+)['\"]", ln)
            if m:
                imps.append(m.group(1))
                continue
            m = re.match(r"^\s*provider\s*=\s*['\"]([^'\"]+)['\"]", ln)
            if m:
                imps.append(m.group(1))
                continue
    elif language == "powershell":
        for ln in lines:
            m = re.match(
                r"^\s*Import-Module\s+([A-Za-z0-9_.\-]+)", ln, flags=re.IGNORECASE
            )
            if m:
                imps.append(m.group(1))
                continue
            m = re.match(r"^\s*using\s+module\s+([^\s;]+)", ln, flags=re.IGNORECASE)
            if m:
                imps.append(m.group(1))
                continue
            m = re.match(r"^\s*using\s+namespace\s+([^\s;]+)", ln, flags=re.IGNORECASE)
            if m:
                imps.append(m.group(1))
                continue
    return imps[:200]


def _extract_calls(language: str, text: str) -> List[str]:
    """Lightweight call-site extraction (best-effort, language-agnostic heuristics)."""
    names: List[str] = []
    # Simple heuristic: word followed by '(' that isn't a keyword
    kw = set([
        "if", "for", "while", "switch", "return", "new",
        "catch", "func", "def", "class", "match",
    ])
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text):
        name = m.group(1)
        if name not in kw:
            names.append(name)
    # Deduplicate preserving order
    out: List[str] = []
    seen = set()
    for n in names:
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out[:200]


# Tree-sitter node type mappings per language
# Maps language -> {calls, constructors, member, class_def, superclass}
# - calls: list of call node types
# - constructors: list of new/object creation node types
# - member: node_type -> (object_field, property_field) for qualified names
# - class_def: node types for class definitions
# - superclass: field name or node types for base classes/inheritance
_TS_LANG_CONFIG = {
    "python": {
        "calls": ["call"],
        "constructors": [],
        "member": {"attribute": ("object", "attribute")},
        "class_def": ["class_definition"],
        "superclass": {"field": "superclasses", "child_types": ["argument_list"]},
    },
    "javascript": {
        "calls": ["call_expression"],
        "constructors": ["new_expression"],
        "member": {"member_expression": ("object", "property")},
        "class_def": ["class_declaration", "class"],
        "superclass": {"field": "heritage", "child_types": ["class_heritage"]},
    },
    "typescript": {
        "calls": ["call_expression"],
        "constructors": ["new_expression"],
        "member": {"member_expression": ("object", "property")},
        "class_def": ["class_declaration", "class"],
        "superclass": {"field": "heritage", "child_types": ["class_heritage", "extends_clause"]},
    },
    "tsx": {
        "calls": ["call_expression"],
        "constructors": ["new_expression"],
        "member": {"member_expression": ("object", "property")},
        "class_def": ["class_declaration", "class"],
        "superclass": {"field": "heritage", "child_types": ["class_heritage", "extends_clause"]},
    },
    "jsx": {
        "calls": ["call_expression"],
        "constructors": ["new_expression"],
        "member": {"member_expression": ("object", "property")},
        "class_def": ["class_declaration", "class"],
        "superclass": {"field": "heritage", "child_types": ["class_heritage"]},
    },
    "go": {
        "calls": ["call_expression"],
        "constructors": [],
        "member": {"selector_expression": ("operand", "field")},
        # Go uses struct embedding, not class inheritance
        "class_def": [],
        "superclass": None,
    },
    "rust": {
        "calls": ["call_expression", "macro_invocation"],
        "constructors": [],
        "member": {"field_expression": ("value", "field")},
        # Rust uses impl blocks for traits, not traditional class inheritance
        # We don't extract INHERITS_FROM for Rust since trait implementations
        # are semantically different from class inheritance
        "class_def": [],
        "superclass": None,
    },
    "java": {
        "calls": ["method_invocation"],
        "constructors": ["object_creation_expression"],
        "member": {"method_invocation": ("object", "name")},
        "class_def": ["class_declaration", "interface_declaration"],
        "superclass": {"field": "superclass", "interfaces_field": "interfaces"},
    },
    "c": {
        "calls": ["call_expression"],
        "constructors": [],
        "member": {"field_expression": ("argument", "field")},
        # C has no class inheritance
        "class_def": [],
        "superclass": None,
    },
    "cpp": {
        "calls": ["call_expression"],
        "constructors": ["new_expression"],
        "member": {
            "field_expression": ("argument", "field"),
            "qualified_identifier": ("scope", "name"),
        },
        "class_def": ["class_specifier", "struct_specifier"],
        "superclass": {"child_types": ["base_class_clause"]},
    },
    "ruby": {
        "calls": ["call", "method_call"],
        "constructors": [],
        "member": {"call": ("receiver", "method")},
        "class_def": ["class"],
        "superclass": {"field": "superclass"},
    },
    "c_sharp": {
        "calls": ["invocation_expression"],
        "constructors": ["object_creation_expression"],
        "member": {"member_access_expression": ("expression", "name")},
        "class_def": ["class_declaration", "interface_declaration"],
        "superclass": {"field": "bases", "child_types": ["base_list"]},
    },
    "csharp": {
        "calls": ["invocation_expression"],
        "constructors": ["object_creation_expression"],
        "member": {"member_access_expression": ("expression", "name")},
        "class_def": ["class_declaration", "interface_declaration"],
        "superclass": {"field": "bases", "child_types": ["base_list"]},
    },
    "bash": {
        "calls": ["command"],
        "constructors": [],
        "member": {},
        "class_def": [],
        "superclass": None,
    },
    "shell": {
        "calls": ["command"],
        "constructors": [],
        "member": {},
        "class_def": [],
        "superclass": None,
    },
    "sh": {
        "calls": ["command"],
        "constructors": [],
        "member": {},
        "class_def": [],
        "superclass": None,
    },
}

# Languages that have tree-sitter call extraction support
# Derived set of languages that support tree-sitter call extraction
_TS_CALL_LANGUAGES = set(_TS_LANG_CONFIG.keys())

# Default config for unknown languages
_TS_DEFAULT_CONFIG = {
    "calls": ["call_expression"],
    "constructors": ["new_expression"],
    "member": {"member_expression": ("object", "property")},
}

# Import node types per language for tree-sitter
_TS_IMPORT_CONFIG = {
    "python": {
        "nodes": ["import_statement", "import_from_statement"],
    },
    "javascript": {
        "nodes": ["import_statement"],
        "source_field": "source",
    },
    "typescript": {
        "nodes": ["import_statement"],
        "source_field": "source",
    },
    "tsx": {
        "nodes": ["import_statement"],
        "source_field": "source",
    },
    "go": {
        "nodes": ["import_declaration"],
    },
    "rust": {
        "nodes": ["use_declaration"],
    },
    "java": {
        "nodes": ["import_declaration"],
    },
    "c": {
        "nodes": ["preproc_include"],
    },
    "cpp": {
        "nodes": ["preproc_include"],
    },
    "c_sharp": {
        "nodes": ["using_directive"],
    },
    "csharp": {
        "nodes": ["using_directive"],
    },
    "ruby": {
        "nodes": ["call"],  # require/require_relative are method calls
    },
    "kotlin": {
        "nodes": ["import"],  # Kotlin uses 'import' node, not 'import_header'
    },
    "swift": {
        "nodes": ["import_declaration"],
    },
    "scala": {
        "nodes": ["import_declaration"],
    },
    "php": {
        "nodes": ["namespace_use_declaration"],
    },
}


def _ts_extract_imports(language: str, text: str) -> List[str]:
    """Extract imports using tree-sitter AST traversal.

    Extracts BOTH module/package names AND specific imported symbols.
    For example:
    - 'from qdrant_client import QdrantClient' -> ['qdrant_client', 'QdrantClient']
    - 'import { Foo, Bar } from "pkg"' -> ['pkg', 'Foo', 'Bar']
    - 'use std::collections::HashMap' -> ['std::collections::HashMap', 'HashMap']

    This enables symbol_graph importers queries to find both module and class/function names.
    """
    from scripts.ingest.tree_sitter import _ts_parser

    if language not in _TS_IMPORT_CONFIG:
        return _extract_imports(language, text)

    parser = _ts_parser(language)
    if not parser:
        return _extract_imports(language, text)

    data = text.encode("utf-8")
    try:
        tree = parser.parse(data)
        if tree is None:
            return _extract_imports(language, text)
        root = tree.root_node
    except Exception:
        return _extract_imports(language, text)

    config = _TS_IMPORT_CONFIG[language]
    import_nodes = set(config["nodes"])

    def node_text(n):
        return data[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

    def is_valid_identifier(name: str) -> bool:
        """Check if name is a valid identifier (not a keyword, operator, etc.)."""
        if not name or len(name) > 100:
            return False
        first = name[0]
        if not (first.isalpha() or first == "_"):
            return False
        return all(c.isalnum() or c == "_" for c in name)

    def find_string_content(node) -> str:
        """Find string literal content from a node."""
        for child in node.children:
            if child.type in ("string", "string_literal", "interpreted_string_literal"):
                txt = node_text(child)
                if len(txt) >= 2 and txt[0] in ('"', "'", "`"):
                    return txt[1:-1]
                return txt
            if child.type in ("import_spec", "import_clause"):
                result = find_string_content(child)
                if result:
                    return result
        return ""

    def extract_scoped_path(node) -> str:
        """Extract path from scoped_identifier (Rust: std::io)."""
        parts = []
        def collect(n):
            if n.type == "identifier":
                parts.append(node_text(n))
            elif n.type in ("crate", "self", "super"):
                parts.append(node_text(n))
            for c in n.children:
                if c.type not in ("::", ".", ";"):
                    collect(c)
        collect(node)
        return "::".join(parts) if parts else node_text(node)

    def extract_leaf_symbol(name: str, sep: str = "::") -> str:
        """Extract the final symbol from a path (e.g., 'std::HashMap' -> 'HashMap')."""
        if sep in name:
            return name.rsplit(sep, 1)[-1]
        if "." in name:
            return name.rsplit(".", 1)[-1]
        return name

    imports: List[str] = []

    def add_import(name: str, also_add_leaf: bool = False, sep: str = "::"):
        """Add import, optionally also adding the leaf symbol."""
        if name and name not in imports:
            imports.append(name)
        if also_add_leaf:
            leaf = extract_leaf_symbol(name, sep)
            if leaf and leaf != name and is_valid_identifier(leaf) and leaf not in imports:
                imports.append(leaf)

    def walk(n):
        ntype = n.type

        if ntype in import_nodes:
            if language == "python":
                # Python handled by _ts_extract_imports_calls_python
                # But keep basic fallback for consistency
                if ntype == "import_statement":
                    for child in n.children:
                        if child.type == "dotted_name":
                            add_import(node_text(child), also_add_leaf=True, sep=".")
                        elif child.type == "aliased_import":
                            name = child.child_by_field_name("name")
                            if name:
                                add_import(node_text(name), also_add_leaf=True, sep=".")
                elif ntype == "import_from_statement":
                    # Get module name
                    module = n.child_by_field_name("module_name")
                    if module:
                        add_import(node_text(module))
                    # Get imported symbols
                    seen_import = False
                    for child in n.children:
                        if child.type == "import":
                            seen_import = True
                        elif seen_import and child.type in ("dotted_name", "identifier"):
                            sym = node_text(child)
                            if sym and is_valid_identifier(sym.split(".")[-1]):
                                add_import(sym)
                        elif child.type == "aliased_import":
                            name_node = child.child_by_field_name("name")
                            if name_node:
                                sym = node_text(name_node)
                                if sym and is_valid_identifier(sym.split(".")[-1]):
                                    add_import(sym)

            elif language in ("javascript", "typescript", "tsx"):
                # JS/TS: import { Foo, Bar } from "pkg" or import Foo from "pkg"
                # Get module path
                source = n.child_by_field_name("source")
                if source:
                    txt = node_text(source)
                    if len(txt) >= 2:
                        add_import(txt[1:-1])
                else:
                    result = find_string_content(n)
                    if result:
                        add_import(result)

                # Get imported symbols from import_clause
                for child in n.children:
                    if child.type == "import_clause":
                        _extract_js_import_symbols(child, imports, node_text)

            elif language == "go":
                # Go: import "path" - no named imports, but add package basename
                for child in n.children:
                    if child.type == "import_spec":
                        result = find_string_content(child)
                        if result:
                            add_import(result, also_add_leaf=True, sep="/")
                    elif child.type == "import_spec_list":
                        for spec in child.children:
                            if spec.type == "import_spec":
                                result = find_string_content(spec)
                                if result:
                                    add_import(result, also_add_leaf=True, sep="/")
                    elif child.type == "interpreted_string_literal":
                        txt = node_text(child)
                        if len(txt) >= 2:
                            add_import(txt[1:-1], also_add_leaf=True, sep="/")

            elif language == "rust":
                # Rust: use std::collections::HashMap or use pkg::{Foo, Bar}
                for child in n.children:
                    if child.type == "scoped_identifier":
                        path = extract_scoped_path(child)
                        add_import(path, also_add_leaf=True)
                    elif child.type == "identifier":
                        add_import(node_text(child))
                    elif child.type == "use_wildcard":
                        path = extract_scoped_path(child)
                        add_import(path)
                    elif child.type == "scoped_use_list":
                        # use pkg::{Foo, Bar}
                        _extract_rust_use_list(child, imports, node_text, extract_scoped_path)
                    elif child.type == "use_list":
                        # Bare use list
                        _extract_rust_use_list_items(child, imports, node_text)

            elif language == "java":
                # Java: import java.util.List - add full path and class name
                for child in n.children:
                    if child.type == "scoped_identifier":
                        path = node_text(child).replace(" ", "")
                        add_import(path, also_add_leaf=True, sep=".")

            elif language in ("c", "cpp"):
                # C/C++: #include <file> - add header name
                path = n.child_by_field_name("path")
                if path:
                    txt = node_text(path)
                    if len(txt) >= 2:
                        header = txt[1:-1]
                        add_import(header)
                        # Also add base name without extension
                        if "/" in header:
                            add_import(header.rsplit("/", 1)[-1])
                else:
                    for child in n.children:
                        if child.type in ("string_literal", "system_lib_string"):
                            txt = node_text(child)
                            if len(txt) >= 2:
                                header = txt[1:-1]
                                add_import(header)

            elif language in ("c_sharp", "csharp"):
                # C#: using System.Text - add full namespace and last part
                for child in n.children:
                    if child.type in ("identifier", "qualified_name"):
                        path = node_text(child)
                        add_import(path, also_add_leaf=True, sep=".")

            elif language == "ruby":
                # Ruby: require is a method call
                if ntype == "call":
                    method = n.child_by_field_name("method")
                    if method and node_text(method) in ("require", "require_relative", "load"):
                        args = n.child_by_field_name("arguments")
                        if args:
                            result = find_string_content(args)
                            if result:
                                add_import(result)

            elif language == "kotlin":
                # Kotlin: import com.pkg.Foo - get qualified_identifier child
                for child in n.children:
                    if child.type == "qualified_identifier":
                        path = node_text(child).replace(" ", "")
                        add_import(path, also_add_leaf=True, sep=".")
                        break
                    elif child.type == "identifier":
                        add_import(node_text(child))

            elif language == "swift":
                # Swift: import Foundation
                for child in n.children:
                    if child.type == "identifier":
                        add_import(node_text(child))

            elif language == "scala":
                # Scala: import java.util.List or import java.util._
                full = node_text(n).replace("import ", "").strip()
                if full:
                    add_import(full, also_add_leaf=True, sep=".")

            elif language == "php":
                # PHP: use Namespace\ClassName - traverse namespace_use_clause -> qualified_name
                for child in n.children:
                    if child.type == "namespace_use_clause":
                        for subchild in child.children:
                            if subchild.type == "qualified_name":
                                path = node_text(subchild).replace("\\\\", "\\")
                                add_import(path, also_add_leaf=True, sep="\\")
                                break
                    elif child.type in ("namespace_name", "qualified_name"):
                        path = node_text(child).replace("\\\\", "\\")
                        add_import(path, also_add_leaf=True, sep="\\")

        for c in n.children:
            walk(c)

    walk(root)

    # Deduplicate preserving order
    seen = set()
    result = []
    for x in imports:
        if x and x not in seen:
            seen.add(x)
            result.append(x)
    return result[:200]


def _extract_js_import_symbols(clause_node, imports: List[str], node_text) -> None:
    """Extract imported symbol names from JS/TS import_clause."""
    for child in clause_node.children:
        if child.type == "identifier":
            # Default import: import Foo from "pkg"
            sym = node_text(child)
            if sym and sym not in imports:
                imports.append(sym)
        elif child.type == "named_imports":
            # Named imports: import { Foo, Bar } from "pkg"
            for spec in child.children:
                if spec.type == "import_specifier":
                    # Get the imported name (or alias)
                    name = spec.child_by_field_name("name")
                    if name:
                        sym = node_text(name)
                        if sym and sym not in imports:
                            imports.append(sym)
                    else:
                        # Fallback: first identifier child
                        for c in spec.children:
                            if c.type == "identifier":
                                sym = node_text(c)
                                if sym and sym not in imports:
                                    imports.append(sym)
                                break
        elif child.type == "namespace_import":
            # Namespace import: import * as utils from "pkg"
            alias = child.child_by_field_name("alias")
            if alias:
                sym = node_text(alias)
                if sym and sym not in imports:
                    imports.append(sym)


def _extract_rust_use_list(scoped_node, imports: List[str], node_text, extract_scoped) -> None:
    """Extract symbols from Rust scoped_use_list: use pkg::{Foo, Bar}."""
    # Get the base path (identifier before ::)
    base_parts = []
    for child in scoped_node.children:
        if child.type == "identifier":
            base_parts.append(node_text(child))
        elif child.type == "scoped_identifier":
            base_parts.append(extract_scoped(child))
        elif child.type == "use_list":
            base = "::".join(base_parts) if base_parts else ""
            if base and base not in imports:
                imports.append(base)
            # Extract items from use_list
            _extract_rust_use_list_items(child, imports, node_text, base)
            break


def _extract_rust_use_list_items(list_node, imports: List[str], node_text, base: str = "") -> None:
    """Extract individual items from a Rust use_list: {Foo, Bar, baz::*}."""
    for child in list_node.children:
        if child.type == "identifier":
            sym = node_text(child)
            if sym and sym not in imports:
                imports.append(sym)
            if base:
                full = f"{base}::{sym}"
                if full not in imports:
                    imports.append(full)
        elif child.type == "scoped_identifier":
            # Nested: baz::Qux
            path = node_text(child).replace(" ", "")
            if path and path not in imports:
                imports.append(path)
            # Also add leaf
            if "::" in path:
                leaf = path.rsplit("::", 1)[-1]
                if leaf and leaf not in imports:
                    imports.append(leaf)
        elif child.type == "use_wildcard":
            path = node_text(child).replace(" ", "")
            if path and path not in imports:
                imports.append(path)


def _ts_extract_calls_generic(language: str, text: str) -> List[str]:
    """Extract function/method calls using tree-sitter AST traversal.

    Uses proper AST node structure - no regex parsing of code text.
    Captures both base names (method) and qualified names (obj.method).
    """
    from scripts.ingest.tree_sitter import _ts_parser

    parser = _ts_parser(language)
    if not parser:
        return _extract_calls(language, text)

    data = text.encode("utf-8")
    try:
        tree = parser.parse(data)
        if tree is None:
            return _extract_calls(language, text)
        root = tree.root_node
    except Exception:
        return _extract_calls(language, text)

    # Get language config
    config = _TS_LANG_CONFIG.get(language, _TS_DEFAULT_CONFIG)
    call_types = set(config["calls"])
    constructor_types = set(config["constructors"])
    member_map = config["member"]  # node_type -> (object_field, property_field)

    def node_text(n):
        return data[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

    def is_valid_identifier(name: str) -> bool:
        """Check if name is a valid identifier (no operators, keywords check skipped for speed)."""
        if not name or len(name) > 100:
            return False
        first = name[0]
        if not (first.isalpha() or first == "_"):
            return False
        return all(c.isalnum() or c == "_" for c in name)

    def extract_from_member(node) -> List[str]:
        """Extract method name and qualified name from member access node using AST structure."""
        names = []
        node_type = node.type

        if node_type not in member_map:
            # Unknown member type - try common field names
            prop = (
                node.child_by_field_name("property") or
                node.child_by_field_name("field") or
                node.child_by_field_name("name") or
                node.child_by_field_name("attribute") or
                node.child_by_field_name("method")
            )
            if prop and prop.type == "identifier":
                method = node_text(prop)
                if is_valid_identifier(method):
                    names.append(method)
            return names

        obj_field, prop_field = member_map[node_type]
        prop_node = node.child_by_field_name(prop_field)
        obj_node = node.child_by_field_name(obj_field)

        # Get method/property name
        method = ""
        if prop_node:
            if prop_node.type in ("identifier", "property_identifier", "field_identifier"):
                method = node_text(prop_node)
            else:
                # Nested - recurse
                nested = extract_from_member(prop_node)
                if nested:
                    method = nested[0]

        if method and is_valid_identifier(method):
            names.append(method)

            # Get object name for qualified form (skip self/this/cls)
            if obj_node:
                obj_name = ""
                if obj_node.type in ("identifier", "this", "self"):
                    obj_name = node_text(obj_node)
                elif obj_node.type in member_map:
                    # Chained: a.b.c -> get "b" from a.b
                    nested = extract_from_member(obj_node)
                    if nested:
                        obj_name = nested[0]

                # Add qualified if object isn't self/this/cls
                if obj_name and obj_name not in ("self", "this", "cls", "super"):
                    if is_valid_identifier(obj_name):
                        names.append(f"{obj_name}.{method}")

        return names

    def extract_function_name(func_node) -> List[str]:
        """Extract function name(s) from the function part of a call expression."""
        if func_node is None:
            return []

        node_type = func_node.type

        # Simple identifier: foo()
        if node_type in ("identifier", "constant", "method_identifier"):
            name = node_text(func_node)
            if is_valid_identifier(name):
                return [name]
            return []

        # Member access: obj.method()
        if node_type in member_map:
            return extract_from_member(func_node)

        # Try common field names for unknown node types
        prop = (
            func_node.child_by_field_name("property") or
            func_node.child_by_field_name("field") or
            func_node.child_by_field_name("name")
        )
        if prop:
            name = node_text(prop)
            if is_valid_identifier(name):
                return [name]

        return []

    def extract_constructor_type(node) -> List[str]:
        """Extract class name from constructor call (new Foo())."""
        type_node = (
            node.child_by_field_name("constructor") or
            node.child_by_field_name("type") or
            node.child_by_field_name("name")
        )
        if not type_node:
            return []

        # Handle generic types: get the base identifier
        if type_node.type in ("identifier", "type_identifier"):
            name = node_text(type_node)
            if is_valid_identifier(name):
                return [name]

        # Generic type: ArrayList<String> - find the identifier child
        if type_node.type in ("generic_type", "parameterized_type"):
            for child in type_node.children:
                if child.type in ("identifier", "type_identifier"):
                    name = node_text(child)
                    if is_valid_identifier(name):
                        return [name]
                    break

        return []

    calls: List[str] = []

    def walk(n):
        ntype = n.type

        # Regular function/method calls
        if ntype in call_types:
            # Java/Kotlin: method_invocation has object+name directly on the node
            if ntype == "method_invocation":
                name_node = n.child_by_field_name("name")
                obj_node = n.child_by_field_name("object")
                if name_node and name_node.type == "identifier":
                    method = node_text(name_node)
                    if is_valid_identifier(method):
                        calls.append(method)
                        # Add qualified name
                        if obj_node and obj_node.type == "identifier":
                            obj = node_text(obj_node)
                            if is_valid_identifier(obj):
                                calls.append(f"{obj}.{method}")
            else:
                # Try standard field names for the function part
                func = (
                    n.child_by_field_name("function") or
                    n.child_by_field_name("method") or
                    n.child_by_field_name("name") or
                    n.child_by_field_name("callee") or
                    n.child_by_field_name("receiver")
                )
                if func:
                    calls.extend(extract_function_name(func))
                else:
                    # Ruby/other: first relevant child
                    for child in n.children:
                        if child.type in ("identifier", "constant", "method_identifier"):
                            name = node_text(child)
                            if is_valid_identifier(name):
                                calls.append(name)
                            break
                        elif child.type in member_map:
                            calls.extend(extract_from_member(child))
                            break

        # Constructor calls
        elif ntype in constructor_types:
            calls.extend(extract_constructor_type(n))

        # Rust macros
        elif ntype == "macro_invocation":
            macro = n.child_by_field_name("macro")
            if macro:
                name = node_text(macro)
                # Strip trailing ! if present in text
                name = name.rstrip("!")
                if is_valid_identifier(name):
                    calls.append(name)

        # Bash commands
        elif ntype == "command":
            cmd = n.child_by_field_name("name")
            if cmd:
                name = node_text(cmd)
                # Allow hyphens in command names
                if name and all(c.isalnum() or c in "_-" for c in name):
                    calls.append(name)

        for c in n.children:
            walk(c)

    walk(root)

    # Deduplicate preserving order
    seen = set()
    result = []
    for x in calls:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result[:200]


from typing import Dict


# Type alias for import map: local_name -> qualified_module_path
ImportMap = Dict[str, str]


def _get_imports_calls(language: str, text: str) -> Tuple[List[str], List[str], ImportMap]:
    """Get imports, calls, and import_map for a file.

    Returns:
        Tuple of (imports, calls, import_map) where:
        - imports: List of imported module/symbol names
        - calls: List of called function/method names
        - import_map: Dict mapping local names to qualified paths for resolution
          e.g., {"QdrantClient": "qdrant_client.QdrantClient"}
    """
    from scripts.ingest.tree_sitter import _use_tree_sitter

    # Use tree-sitter for Python (specialized) or generic for other supported languages
    if _use_tree_sitter():
        if language == "python":
            return _ts_extract_imports_calls_python(text)
        elif language in _TS_CALL_LANGUAGES:
            # Use tree-sitter for both imports and calls
            imports = _ts_extract_imports(language, text)
            calls = _ts_extract_calls_generic(language, text)
            # Build import_map from imports list for non-Python languages
            import_map = _build_import_map_generic(language, imports)
            return imports, calls, import_map

    imports = _extract_imports(language, text)
    calls = _extract_calls(language, text)
    import_map = _build_import_map_generic(language, imports)
    return imports, calls, import_map


# Type alias for inheritance info: {class_name: [base_class_names]}
InheritanceMap = Dict[str, List[str]]


def _get_inheritance(language: str, text: str) -> InheritanceMap:
    """Extract class inheritance relationships using tree-sitter.

    Returns:
        Dict mapping class names to their list of base classes.
        e.g., {"MyClass": ["BaseClass", "Mixin"], "Child": ["Parent"]}
    """
    from scripts.ingest.tree_sitter import _use_tree_sitter, _ts_parser

    if not _use_tree_sitter():
        return {}

    config = _TS_LANG_CONFIG.get(language, _TS_DEFAULT_CONFIG)
    class_def_types = set(config.get("class_def", []))
    superclass_config = config.get("superclass")

    if not class_def_types or superclass_config is None:
        return {}

    parser = _ts_parser(language)
    if not parser:
        return {}

    data = text.encode("utf-8")
    try:
        tree = parser.parse(data)
        if tree is None:
            return {}
        root = tree.root_node
    except Exception:
        return {}

    def node_text(n):
        return data[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

    def is_valid_identifier(name: str) -> bool:
        if not name or len(name) > 100:
            return False
        first = name[0]
        if not (first.isalpha() or first == "_"):
            return False
        return all(c.isalnum() or c == "_" for c in name)

    def extract_identifiers(node) -> List[str]:
        """Recursively extract identifier names from a node."""
        names = []
        if node.type in ("identifier", "type_identifier"):
            name = node_text(node)
            if is_valid_identifier(name):
                names.append(name)
        for child in node.children:
            names.extend(extract_identifiers(child))
        return names

    inheritance: InheritanceMap = {}

    def walk(node):
        if node.type in class_def_types:
            # Get class name
            name_node = node.child_by_field_name("name")
            class_name = node_text(name_node) if name_node else ""

            if class_name and is_valid_identifier(class_name):
                bases = []

                # Try field-based access first
                if isinstance(superclass_config, dict):
                    field_name = superclass_config.get("field")
                    if field_name:
                        superclass_node = node.child_by_field_name(field_name)
                        if superclass_node:
                            bases.extend(extract_identifiers(superclass_node))

                    # Also check interfaces/implements field (Java)
                    interfaces_field = superclass_config.get("interfaces_field")
                    if interfaces_field:
                        interfaces_node = node.child_by_field_name(interfaces_field)
                        if interfaces_node:
                            bases.extend(extract_identifiers(interfaces_node))

                    # Check child node types ONLY if field access didn't find anything
                    if not bases:
                        child_types = superclass_config.get("child_types", [])
                        if child_types:
                            for child in node.children:
                                if child.type in child_types:
                                    bases.extend(extract_identifiers(child))

                # Deduplicate while preserving order
                if bases:
                    seen = set()
                    unique_bases = []
                    for b in bases:
                        if b not in seen:
                            seen.add(b)
                            unique_bases.append(b)
                    bases = unique_bases

                if bases:
                    # Filter out common non-base identifiers
                    filtered = [b for b in bases if b.lower() not in ("object", "none", "null")]
                    if filtered:
                        inheritance[class_name] = filtered

        for child in node.children:
            walk(child)

    walk(root)
    return inheritance


def _build_import_map_generic(language: str, imports: List[str]) -> ImportMap:
    """Build import_map from imports list for non-Python languages.

    For languages without specialized extractors, we create basic mappings:
    - "module.Symbol" -> {"Symbol": "module.Symbol"}
    - "pkg::Type" -> {"Type": "pkg::Type"} (Rust)
    """
    import_map: ImportMap = {}

    for imp in imports:
        if not imp:
            continue

        # Determine separator based on language
        if language == "rust":
            sep = "::"
        elif language in ("java", "csharp", "php"):
            sep = "."
        elif language in ("javascript", "typescript", "tsx"):
            # JS/TS imports are paths, the leaf is typically a module name
            sep = "/"
        else:
            sep = "."

        # Extract leaf name and map it
        if sep in imp:
            parts = imp.rsplit(sep, 1)
            if len(parts) == 2:
                leaf = parts[1]
                if leaf and len(leaf) < 100:
                    import_map[leaf] = imp
        else:
            # Simple import - map to itself
            import_map[imp] = imp

    return import_map


def _ts_extract_imports_calls_python(text: str) -> Tuple[List[str], List[str], ImportMap]:
    """Extract imports, calls, and import_map from Python using tree-sitter AST.

    Returns:
        Tuple of (imports, calls, import_map) where import_map maps local names
        to qualified module paths for resolution.

    Example import_map:
        from qdrant_client import QdrantClient  -> {"QdrantClient": "qdrant_client.QdrantClient"}
        from qdrant_client import models as qm  -> {"qm": "qdrant_client.models"}
        import os.path                          -> {"os": "os", "path": "os.path"}
    """
    from scripts.ingest.tree_sitter import _ts_parser

    parser = _ts_parser("python")
    if not parser:
        return [], [], {}
    data = text.encode("utf-8")
    try:
        tree = parser.parse(data)
        if tree is None:
            return [], [], {}
        root = tree.root_node
    except (ValueError, Exception):
        return [], [], {}

    def node_text(n):
        return data[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")

    def is_valid_identifier(name: str) -> bool:
        if not name or len(name) > 100:
            return False
        first = name[0]
        if not (first.isalpha() or first == "_"):
            return False
        return all(c.isalnum() or c == "_" for c in name)

    imports: List[str] = []
    calls: List[str] = []
    import_map: ImportMap = {}  # local_name -> qualified_path

    def extract_python_call(func_node) -> List[str]:
        """Extract call names from Python function node using AST structure."""
        if func_node is None:
            return []

        # Simple identifier: foo()
        if func_node.type == "identifier":
            name = node_text(func_node)
            if is_valid_identifier(name):
                return [name]
            return []

        # Attribute access: obj.method()
        if func_node.type == "attribute":
            names = []
            # Python attribute node has: object and attribute fields
            attr_node = func_node.child_by_field_name("attribute")
            value_node = func_node.child_by_field_name("object")

            method = ""
            if attr_node and attr_node.type == "identifier":
                method = node_text(attr_node)

            if method and is_valid_identifier(method):
                names.append(method)

                # Get object for qualified name
                if value_node:
                    obj_name = ""
                    if value_node.type == "identifier":
                        obj_name = node_text(value_node)
                    elif value_node.type == "attribute":
                        # Chained: a.b.method - get "b" from a.b
                        nested_attr = value_node.child_by_field_name("attribute")
                        if nested_attr and nested_attr.type == "identifier":
                            obj_name = node_text(nested_attr)

                    # Add qualified if not self/cls/super
                    if obj_name and obj_name not in ("self", "cls", "super"):
                        if is_valid_identifier(obj_name):
                            names.append(f"{obj_name}.{method}")

            return names

        return []

    def extract_import_module(node) -> str:
        """Extract module name from import node using AST structure."""
        # For import_statement: import foo.bar
        # For import_from_statement: from foo.bar import baz
        # Look for dotted_name or aliased_import children
        for child in node.children:
            if child.type == "dotted_name":
                return node_text(child)
            elif child.type == "aliased_import":
                # import foo as f -> get "foo"
                name_child = child.child_by_field_name("name")
                if name_child:
                    return node_text(name_child)
        return ""

    def extract_from_import_symbols(node) -> Tuple[str, List[str], Dict[str, str]]:
        """Extract module, imported symbols, and alias mappings from import_from_statement.

        For 'from X import Y, Z as A' returns:
          - module_name: 'X'
          - imported_symbols: ['Y', 'Z']
          - mappings: {'Y': 'X.Y', 'A': 'X.Z'}  # local_name -> qualified_path
        """
        module_name = ""
        imported_symbols = []
        mappings: Dict[str, str] = {}  # local_name -> qualified_path
        seen_import_keyword = False

        for child in node.children:
            if child.type == "from":
                continue
            elif child.type == "import":
                seen_import_keyword = True
                continue
            elif child.type == ",":
                continue
            elif child.type in ("dotted_name", "identifier"):
                name = node_text(child)
                if not seen_import_keyword:
                    # Before 'import' keyword = module name
                    module_name = name
                else:
                    # After 'import' keyword = imported symbol (no alias)
                    if name and is_valid_identifier(name.split(".")[-1]):
                        imported_symbols.append(name)
                        # Will populate mappings after we have module_name
            elif child.type == "relative_import":
                # Handle relative imports: from . import X or from ..parent import X
                for rel_child in child.children:
                    if rel_child.type == "dotted_name":
                        module_name = node_text(rel_child)
                        break
            elif child.type == "aliased_import":
                # from X import Y as Z -> local name is Z, qualified is X.Y
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node:
                    orig_name = node_text(name_node)
                    local_name = node_text(alias_node) if alias_node else orig_name
                    if orig_name and is_valid_identifier(orig_name.split(".")[-1]):
                        imported_symbols.append(orig_name)
                        # Build mapping: alias -> module.original
                        if local_name and module_name:
                            mappings[local_name] = f"{module_name}.{orig_name}"
                        elif local_name:
                            # Placeholder - will fix after we have module_name
                            mappings[local_name] = orig_name

        # Build mappings for non-aliased imports
        if module_name:
            for sym in imported_symbols:
                if sym not in mappings:
                    mappings[sym] = f"{module_name}.{sym}"

        return module_name, imported_symbols, mappings

    def extract_import_statement_mappings(node) -> Dict[str, str]:
        """Extract mappings from 'import X' or 'import X as Y' statements.

        Examples:
          import os           -> {"os": "os"}
          import os.path      -> {"os": "os", "path": "os.path"}
          import numpy as np  -> {"np": "numpy"}
        """
        mappings: Dict[str, str] = {}
        for child in node.children:
            if child.type == "dotted_name":
                mod = node_text(child)
                if mod:
                    # For 'import os.path', local name is 'os' (top-level)
                    top = mod.split(".")[0]
                    mappings[top] = top
                    # Also map the full path
                    if "." in mod:
                        mappings[mod] = mod
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node:
                    orig = node_text(name_node)
                    local = node_text(alias_node) if alias_node else orig
                    if orig and local:
                        mappings[local] = orig
        return mappings

    def walk(n):
        t = n.type
        if t == "import_statement":
            mod = extract_import_module(n)
            if mod:
                imports.append(mod)
            # Also extract mappings for resolution
            stmt_mappings = extract_import_statement_mappings(n)
            import_map.update(stmt_mappings)
        elif t == "import_from_statement":
            # from X import Y, Z -> store both X (module) and Y, Z (symbols)
            module_name, imported_syms, sym_mappings = extract_from_import_symbols(n)
            if module_name:
                imports.append(module_name)
            # Also add imported symbols for direct lookups (e.g., "QdrantClient")
            for sym in imported_syms:
                if sym and sym not in imports:
                    imports.append(sym)
            # Update import_map with qualified paths
            import_map.update(sym_mappings)
        elif t == "call":
            func = n.child_by_field_name("function")
            if func:
                calls.extend(extract_python_call(func))

        for c in n.children:
            walk(c)

    walk(root)

    # Deduplicate preserving order
    seen = set()
    calls_dedup = []
    for x in calls:
        if x not in seen:
            seen.add(x)
            calls_dedup.append(x)
    return imports[:200], calls_dedup[:200], import_map


def _get_host_path_from_origin(workspace_path: str, repo_name: str = None) -> Optional[str]:
    """Get client host_path from origin source_path in workspace state."""
    try:
        from scripts.workspace_state import get_workspace_state
        state = get_workspace_state(workspace_path, repo_name)
        if state and state.get("origin", {}).get("source_path"):
            return state["origin"]["source_path"]
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")
    return None


def _compute_host_and_container_paths(cur_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Compute host_path and container_path for a given absolute path."""
    _host_root = str(os.environ.get("HOST_INDEX_PATH") or "").strip().rstrip("/")
    if ":" in _host_root:
        _host_root = ""
    _host_path: Optional[str] = None
    _container_path: Optional[str] = None
    _origin_client_path: Optional[str] = None

    try:
        if cur_path.startswith("/work/"):
            _parts = cur_path[6:].split("/")
            if len(_parts) >= 2:
                _repo_name = _parts[0]
                _workspace_path = f"/work/{_repo_name}"
                _origin_client_path = _get_host_path_from_origin(
                    _workspace_path, _repo_name
                )
    except Exception:
        _origin_client_path = None

    try:
        if cur_path.startswith("/work/") and (_host_root or _origin_client_path):
            _rel = cur_path[len("/work/"):]
            if _origin_client_path:
                _parts = _rel.split("/", 1)
                _tail = _parts[1] if len(_parts) > 1 else ""
                _base = _origin_client_path.rstrip("/")
                _host_path = (
                    os.path.realpath(os.path.join(_base, _tail)) if _tail else _base
                )
            else:
                _host_path = os.path.realpath(os.path.join(_host_root, _rel))
            _container_path = cur_path
        else:
            _host_path = cur_path
            if (
                (_host_root or _origin_client_path)
                and cur_path.startswith(((_origin_client_path or _host_root) + "/"))
            ):
                _rel = cur_path[len((_origin_client_path or _host_root)) + 1:]
                _container_path = "/work/" + _rel
    except Exception:
        _host_path = cur_path
        _container_path = cur_path if cur_path.startswith("/work/") else None

    return _host_path, _container_path
