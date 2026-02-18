"""Pascal/Delphi language mapping for the unified parser architecture.

Provides Pascal/Delphi-specific tree-sitter queries and regex-based
extraction logic for semantic chunking and symbol extraction.

Supports .pas, .dpr, .dpk, .lpr files (Object Pascal / Delphi / Lazarus).
Uses tree-sitter queries when the pascal grammar is available,
with a regex-based fallback for all ConceptTypes.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

from .base import BaseMapping, ConceptType, MAX_CONSTANT_VALUE_LENGTH

if TYPE_CHECKING:
    from tree_sitter import Node as TSNode


# RTL/VCL/FMX standard units — filtered out during import resolution
PASCAL_BUILTIN_UNIT_PREFIXES = (
    'System.', 'Winapi.', 'Vcl.', 'Fmx.', 'Data.', 'Datasnap.',
    'Web.', 'Soap.', 'Xml.', 'Bde.', 'Ibd.', 'Dbx.',
)

PASCAL_BUILTIN_UNITS = frozenset({
    'System', 'SysUtils', 'Classes', 'Types', 'Variants', 'StrUtils',
    'Math', 'DateUtils', 'IOUtils', 'AnsiStrings', 'Character',
    'Generics.Collections', 'Generics.Defaults',
    'SyncObjs', 'SysConst', 'RTLConsts',
    'Windows', 'Messages', 'ShellAPI',
    'Dialogs', 'Forms', 'Controls', 'StdCtrls', 'ExtCtrls',
    'Menus', 'ComCtrls', 'Graphics', 'Buttons', 'CheckLst',
    'DBCtrls', 'DBGrids', 'DB', 'DBTables',
})

# Pascal reserved words to skip during import extraction
_PASCAL_RESERVED = frozenset({
    'uses', 'in', 'interface', 'implementation', 'unit', 'program',
    'package', 'library', 'initialization', 'finalization', 'end',
    'begin', 'type', 'var', 'const', 'procedure', 'function',
    'class', 'record', 'object', 'array', 'string', 'integer',
    'boolean', 'byte', 'word', 'cardinal', 'int64', 'double',
    'single', 'extended', 'currency', 'char', 'widechar', 'ansichar',
    'shortint', 'smallint', 'longint', 'longword', 'uint64',
    'pointer', 'nil', 'true', 'false', 'inherited', 'override',
    'virtual', 'abstract', 'published', 'public', 'private',
    'protected', 'property', 'read', 'write', 'default', 'stored',
    'constructor', 'destructor', 'if', 'then', 'else', 'for', 'to',
    'downto', 'do', 'while', 'repeat', 'until', 'case', 'of',
    'with', 'raise', 'try', 'except', 'finally', 'on', 'not', 'and',
    'or', 'xor', 'div', 'mod', 'shl', 'shr', 'is', 'as',
    'exit', 'break', 'continue', 'goto', 'label', 'packed', 'set',
    'file', 'forward', 'external', 'cdecl', 'stdcall', 'register',
    'pascal', 'safecall', 'assembler', 'inline', 'static', 'dynamic',
    'message', 'dispinterface', 'automation', 'implements', 'reintroduce',
    'overload', 'result', 'self', 'resourcestring',
})

# --- Regex patterns for tree-sitter fallback ---

# Type declarations: TMyClass = class(...), TMyRecord = record, IMyIntf = interface
_RE_CLASS = re.compile(
    r"^\s*(T\w+)\s*=\s*(?:class|record)\b",
    re.IGNORECASE | re.MULTILINE,
)
_RE_INTERFACE_DECL = re.compile(
    r"^\s*(I\w+)\s*=\s*interface\b",
    re.IGNORECASE | re.MULTILINE,
)
_RE_TYPE_ALIAS = re.compile(
    r"^\s*(T\w+)\s*=\s*(?!class\b|record\b|interface\b|\()(\w[\w\.\[\]]*)",
    re.IGNORECASE | re.MULTILINE,
)
# Methods: procedure TMyClass.DoWork; / function TMyClass.GetValue: Integer;
_RE_METHOD_IMPL = re.compile(
    r"^\s*(?:class\s+)?(?:procedure|function|constructor|destructor)\s+"
    r"(T\w+\.\w+)\s*(?:\(|;|:|\s)",
    re.IGNORECASE | re.MULTILINE,
)
# Standalone procedures/functions (no class prefix)
_RE_STANDALONE_PROC = re.compile(
    r"^\s*(?:procedure|function)\s+([A-Za-z_]\w+)\s*(?:\(|;)",
    re.IGNORECASE | re.MULTILINE,
)
# Module declaration: unit X; / program X; / package X;
_RE_MODULE = re.compile(
    r"^\s*(?:unit|program|package|library)\s+([A-Za-z_][\w\.]*)\s*;",
    re.IGNORECASE | re.MULTILINE,
)


class PascalMapping(BaseMapping):
    """Pascal/Delphi (Object Pascal) language mapping.

    Supports .pas, .dpr, .dpk, .lpr files.
    Tree-sitter queries use the Isopod/tree-sitter-pascal grammar node types.
    Falls back to regex if tree-sitter grammar is unavailable.
    """

    def __init__(self) -> None:
        """Initialize Pascal mapping."""
        super().__init__("pascal")

    # -------------------------------------------------------------------------
    # Tree-sitter queries (Isopod/tree-sitter-pascal grammar)
    # -------------------------------------------------------------------------

    def get_query_for_concept(self, concept: ConceptType) -> Optional[str]:
        """Get tree-sitter query for universal concept in Pascal.

        Returns None for concepts without a matching tree-sitter query,
        or when tree-sitter-pascal is not available.
        """
        if concept == ConceptType.DEFINITION:
            return """
            ; Type declarations (includes classes, records, etc.)
            (declType
                name: (identifier) @name
            ) @definition

            ; Procedures and functions (standalone or method implementations)
            (declProc
                name: (identifier) @name
            ) @definition

            ; Constant declarations
            (declConst
                name: (identifier) @name
            ) @definition
            """

        elif concept == ConceptType.IMPORT:
            return """
            (declUses
                (moduleName) @name
            ) @definition
            """

        elif concept == ConceptType.COMMENT:
            return """
            (comment) @definition
            """

        elif concept == ConceptType.STRUCTURE:
            return """
            (module
                name: (identifier) @name
            ) @definition
            """

        return None

    # -------------------------------------------------------------------------
    # Name extraction
    # -------------------------------------------------------------------------

    def extract_name(
        self,
        concept: ConceptType,
        captures: Dict[str, Any],
        content: bytes,
    ) -> str:
        """Extract name from tree-sitter captures."""
        source = content.decode("utf-8", errors="replace")

        if concept == ConceptType.DEFINITION:
            if "name" in captures:
                return self.get_node_text(captures["name"], source).strip()
            def_node = captures.get("definition")
            if def_node:
                return self.get_fallback_name(def_node, "definition")
            return "unnamed_definition"

        elif concept == ConceptType.COMMENT:
            def_node = captures.get("definition")
            if def_node:
                line = def_node.start_point[0] + 1
                return f"comment_line_{line}"
            return "unnamed_comment"

        elif concept == ConceptType.IMPORT:
            if "name" in captures:
                return self.get_node_text(captures["name"], source).strip()
            if "definition" in captures:
                return self.get_node_text(captures["definition"], source).strip()
            return "unnamed_import"

        elif concept == ConceptType.STRUCTURE:
            if "name" in captures:
                return self.get_node_text(captures["name"], source).strip()
            return "module"

        return "unnamed"

    # -------------------------------------------------------------------------
    # Content extraction
    # -------------------------------------------------------------------------

    def extract_content(
        self,
        concept: ConceptType,
        captures: Dict[str, Any],
        content: bytes,
    ) -> str:
        """Extract content text from tree-sitter captures."""
        source = content.decode("utf-8", errors="replace")

        if "definition" in captures:
            node = captures["definition"]
            return self.get_node_text(node, source)
        if captures:
            node = list(captures.values())[0]
            return self.get_node_text(node, source)
        return ""

    # -------------------------------------------------------------------------
    # Metadata extraction
    # -------------------------------------------------------------------------

    def extract_metadata(
        self,
        concept: ConceptType,
        captures: Dict[str, Any],
        content: bytes,
    ) -> Dict[str, Any]:
        """Extract Pascal-specific metadata including kind classification.

        Kind values:
        - ``class`` — class or record type declaration
        - ``interface`` — interface type declaration
        - ``method`` — procedure/function with class prefix (TFoo.Bar)
        - ``function`` — standalone procedure or function
        - ``enum`` — enumeration type
        - ``constant`` — named constant
        - ``type_alias`` — type alias declaration
        - ``import`` — uses-clause unit reference
        """
        source = content.decode("utf-8", errors="replace")
        metadata: Dict[str, Any] = {}

        if concept == ConceptType.DEFINITION:
            def_node = captures.get("definition")
            if def_node:
                metadata["node_type"] = def_node.type
                node_text = self.get_node_text(def_node, source).strip()

                if def_node.type == "declType":
                    kind = _classify_type_decl(node_text)
                elif def_node.type == "declProc":
                    name_node = captures.get("name")
                    name = self.get_node_text(name_node, source).strip() if name_node else ""
                    # Method implementations have a dotted name (e.g. TClass.Method)
                    kind = "method" if "." in name else "function"
                elif def_node.type == "declConst":
                    kind = "constant"
                else:
                    kind = "unknown"

                metadata["kind"] = kind

        elif concept == ConceptType.IMPORT:
            metadata["kind"] = "import"

        return metadata

    # -------------------------------------------------------------------------
    # Import module extraction
    # -------------------------------------------------------------------------

    def get_import_module(self, import_text: str) -> Optional[str]:
        """Extract and filter the unit name from a uses-clause entry.

        Filters out RTL/VCL/FMX built-in units to reduce noise.

        Returns:
            Unit name, or ``None`` for built-in/standard units.
        """
        unit = import_text.strip().split()[0].rstrip(";,")
        if not unit:
            return None
        # Filter known built-in unit prefixes
        for prefix in PASCAL_BUILTIN_UNIT_PREFIXES:
            if unit.startswith(prefix):
                return None
        # Filter known built-in unit names
        if unit in PASCAL_BUILTIN_UNITS:
            return None
        return unit

    # -------------------------------------------------------------------------
    # Regex-based fallback extraction (used when tree-sitter is unavailable)
    # -------------------------------------------------------------------------

    def extract_definitions_regex(self, text: str) -> List[Dict[str, Any]]:
        """Extract definitions using regex fallback.

        Returns a list of dicts with ``name``, ``kind``, ``start_line``,
        ``end_line`` for each definition found.
        """
        # Strip BOM if present (Delphi UTF-8 with BOM)
        clean = text.lstrip("\ufeff")
        results: List[Dict[str, Any]] = []

        for m in _RE_CLASS.finditer(clean):
            line = clean[:m.start()].count("\n") + 1
            results.append({
                "name": m.group(1),
                "kind": "class",
                "start_line": line,
                "end_line": line,
                "content": m.group(0).strip(),
            })

        for m in _RE_INTERFACE_DECL.finditer(clean):
            line = clean[:m.start()].count("\n") + 1
            results.append({
                "name": m.group(1),
                "kind": "interface",
                "start_line": line,
                "end_line": line,
                "content": m.group(0).strip(),
            })

        for m in _RE_METHOD_IMPL.finditer(clean):
            line = clean[:m.start()].count("\n") + 1
            results.append({
                "name": m.group(1),
                "kind": "method",
                "start_line": line,
                "end_line": line,
                "content": m.group(0).strip(),
            })

        for m in _RE_STANDALONE_PROC.finditer(clean):
            line = clean[:m.start()].count("\n") + 1
            # Skip if name contains a dot (already handled as method)
            if "." not in m.group(1):
                results.append({
                    "name": m.group(1),
                    "kind": "function",
                    "start_line": line,
                    "end_line": line,
                    "content": m.group(0).strip(),
                })

        return results

    def extract_imports_regex(self, text: str) -> List[str]:
        """Extract unit names from uses clause using regex.

        Handles single-line and multi-line uses blocks.
        Filters out reserved words.
        """
        clean = text.lstrip("\ufeff")
        imports: List[str] = []
        in_uses = False

        for line in clean.splitlines():
            stripped = line.strip()
            if re.match(r"^\s*uses\b", stripped, re.IGNORECASE):
                in_uses = True
            if in_uses:
                for m in re.finditer(r"\b([A-Za-z_][\w\.]*)\b", stripped):
                    unit = m.group(1)
                    if unit.lower() not in _PASCAL_RESERVED:
                        imports.append(unit)
                if ";" in stripped:
                    in_uses = False

        return imports


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _classify_type_decl(node_text: str) -> str:
    """Classify a Pascal type declaration into a semantic kind.

    Args:
        node_text: Raw text of the declType node.

    Returns:
        One of ``class``, ``interface``, ``enum``, ``type_alias``.
    """
    lower = node_text.lower()
    if re.search(r"=\s*(?:class|record)\b", lower):
        return "class"
    if re.search(r"=\s*interface\b", lower):
        return "interface"
    if re.search(r"=\s*\(", node_text):
        return "enum"
    return "type_alias"
