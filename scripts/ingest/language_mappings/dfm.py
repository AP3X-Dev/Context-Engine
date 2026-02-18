"""DFM/FMX form file mapping for the unified parser architecture.

Provides regex-based extraction for Delphi VCL/FireMonkey form files (.dfm, .fmx).
These files do not use tree-sitter (no grammar available); all extraction is
regex-based.

DFM format overview::

    object Form1: TForm1
      Left = 0
      Top = 0
      Caption = 'Hello World'
      object Button1: TButton
        Left = 100
        Caption = 'Click me'
        OnClick = Button1Click
      end
    end
"""

import re
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

from .base import BaseMapping, ConceptType


# Matches: object ComponentName: TComponentType
_RE_OBJECT = re.compile(
    r"^\s*(object|inherited)\s+(\w+)\s*:\s*(\w+)\s*$",
    re.IGNORECASE,
)
# Matches event handler assignments: OnClick = ButtonClickHandler
_RE_EVENT = re.compile(
    r"^\s*(On\w+)\s*=\s*(\w+)\s*$",
    re.IGNORECASE,
)
# Matches start of multi-line property value: PropName = (
_RE_MULTILINE_START = re.compile(r"^\s*\w[\w\.]*\s*=\s*\(")
# Matches <item> … </item> start
_RE_ITEM_START = re.compile(r"^\s*<item\s*>?\s*$", re.IGNORECASE)
_RE_ITEM_END = re.compile(r"^\s*</item\s*>\s*$", re.IGNORECASE)


class DfmMapping(BaseMapping):
    """DFM/FMX Delphi form file mapping (regex-based, no tree-sitter).

    Extracts component objects from ``object Name: TType ... end`` blocks
    and event handler references (``OnEvent = HandlerMethod``).
    """

    def __init__(self) -> None:
        """Initialize DFM mapping."""
        super().__init__("dfm")

    # -------------------------------------------------------------------------
    # Tree-sitter — not supported for DFM/FMX
    # -------------------------------------------------------------------------

    def get_query_for_concept(self, concept: ConceptType) -> Optional[str]:
        """DFM/FMX files do not support tree-sitter queries.

        Always returns ``None``.
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
        """Extract name from captures.

        For DFM the captures dict is populated by custom regex extraction,
        not tree-sitter; the ``name`` key holds the component name.
        """
        return captures.get("name", "unnamed_component")  # type: ignore[return-value]

    # -------------------------------------------------------------------------
    # Content extraction
    # -------------------------------------------------------------------------

    def extract_content(
        self,
        concept: ConceptType,
        captures: Dict[str, Any],
        content: bytes,
    ) -> str:
        """Return the raw text segment for the matched component."""
        return captures.get("content", "")  # type: ignore[return-value]

    # -------------------------------------------------------------------------
    # Metadata extraction
    # -------------------------------------------------------------------------

    def extract_metadata(
        self,
        concept: ConceptType,
        captures: Dict[str, Any],
        content: bytes,
    ) -> Dict[str, Any]:
        """Return DFM-specific metadata.

        Keys returned:
        - ``kind``: always ``"component"``
        - ``component_type``: the Delphi class name (e.g. ``TButton``)
        - ``events``: list of ``{"event": name, "handler": method}`` dicts
        - ``depth``: nesting depth (0 = root form)
        """
        metadata: Dict[str, Any] = {
            "kind": "component",
            "component_type": captures.get("component_type", ""),
            "events": captures.get("events", []),
            "depth": captures.get("depth", 0),
        }
        return metadata

    # -------------------------------------------------------------------------
    # DFM-specific helper: extract all components from form source
    # -------------------------------------------------------------------------

    def extract_components(self, text: str) -> List[Dict[str, Any]]:
        """Parse a DFM/FMX file and return a list of component dicts.

        Each dict contains:
        - ``name``: component name
        - ``component_type``: Delphi class (e.g. ``TButton``)
        - ``kind``: ``"component"``
        - ``start_line``: 1-based line number of ``object`` keyword
        - ``end_line``: 1-based line number of matching ``end``
        - ``depth``: nesting depth (0 = the form itself)
        - ``events``: list of ``{"event": str, "handler": str}``
        - ``parent``: name of enclosing component, or ``""`` for root

        Args:
            text: Full DFM/FMX file content as a string.

        Returns:
            List of component dicts in declaration order.
        """
        lines = text.splitlines()
        components: List[Dict[str, Any]] = []
        # Stack of (component_dict, indent_level)
        stack: List[Dict[str, Any]] = []
        skip_depth = 0   # skip_depth > 0 means we are inside a block to skip
        paren_depth = 0  # for multi-line parenthesised property values

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()

            # --- Skip multi-line property values (e.g. Items.Strings = (...))
            if paren_depth > 0:
                paren_depth += stripped.count("(")
                paren_depth -= stripped.count(")")
                if paren_depth < 0:
                    paren_depth = 0
                continue

            if _RE_MULTILINE_START.match(line):
                paren_depth = 1
                continue

            # --- Skip <item> ... </item> collection entries
            if skip_depth > 0:
                if _RE_ITEM_START.match(line):
                    skip_depth += 1
                elif _RE_ITEM_END.match(line):
                    skip_depth -= 1
                continue

            if _RE_ITEM_START.match(line):
                skip_depth += 1
                continue

            # --- Component declaration
            m_obj = _RE_OBJECT.match(line)
            if m_obj:
                keyword = m_obj.group(1).lower()
                comp_name = m_obj.group(2)
                comp_type = m_obj.group(3)
                parent_name = stack[-1]["name"] if stack else ""
                depth = len(stack)

                comp: Dict[str, Any] = {
                    "name": comp_name,
                    "component_type": comp_type,
                    "kind": "component",
                    "start_line": line_idx,
                    "end_line": line_idx,
                    "depth": depth,
                    "events": [],
                    "parent": parent_name,
                    "inherited": keyword == "inherited",
                }
                stack.append(comp)
                components.append(comp)
                continue

            # --- End of component block
            if stripped.lower() == "end":
                if stack:
                    finished = stack.pop()
                    finished["end_line"] = line_idx
                continue

            # --- Event handler assignment
            m_event = _RE_EVENT.match(line)
            if m_event and stack:
                stack[-1]["events"].append({
                    "event": m_event.group(1),
                    "handler": m_event.group(2),
                })
                continue

        return components
