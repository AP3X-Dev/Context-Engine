"""Base mapping class for language-specific tree-sitter mappings.

Provides concept-based extraction (DEFINITION, BLOCK, COMMENT, IMPORT, STRUCTURE)
for semantic chunking and symbol extraction.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Any, Dict, Iterator, List, Optional

try:
    from tree_sitter import Node as TSNode
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    TSNode = Any  # type: ignore

logger = logging.getLogger(__name__)

# Maximum length for constant values in metadata (prevents bloat)
MAX_CONSTANT_VALUE_LENGTH = 50


class ConceptType(Enum):
    """Universal semantic concepts found in programming languages."""
    DEFINITION = "definition"  # Functions, classes, types, constants
    BLOCK = "block"            # Control flow blocks, scoped regions
    COMMENT = "comment"        # Comments, docstrings
    IMPORT = "import"          # Import/include statements
    STRUCTURE = "structure"    # File-level structure


@dataclass
class ConceptResult:
    """Result of concept extraction."""
    concept: ConceptType
    name: str
    content: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    kind: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseMapping(ABC):
    """Base class for language-specific tree-sitter mappings."""

    def __init__(self, language: str):
        self.language = language

    # -------------------------------------------------------------------------
    # Abstract methods - subclasses must implement
    # -------------------------------------------------------------------------
    
    @abstractmethod
    def get_query_for_concept(self, concept: ConceptType) -> Optional[str]:
        """Get tree-sitter query for a concept type. Returns None if unsupported."""
        pass

    @abstractmethod
    def extract_name(self, concept: ConceptType, captures: Dict[str, Any], content: bytes) -> str:
        """Extract name from query captures."""
        pass

    @abstractmethod
    def extract_content(self, concept: ConceptType, captures: Dict[str, Any], content: bytes) -> str:
        """Extract content from query captures."""
        pass

    # -------------------------------------------------------------------------
    # Optional methods with defaults
    # -------------------------------------------------------------------------

    def extract_metadata(self, concept: ConceptType, captures: Dict[str, Any], content: bytes) -> Dict[str, Any]:
        """Extract metadata from query captures. Override for language-specific metadata."""
        return {}

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def get_node_text(self, node: Any, source: str) -> str:
        """Get text content of a tree-sitter node."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return ""
        source_bytes = source.encode("utf-8")
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def find_child_by_type(self, node: Any, node_type: str) -> Optional[Any]:
        """Find first child of specified type."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return None
        for i in range(node.child_count):
            child = node.child(i)
            if child and child.type == node_type:
                return child
        return None

    def find_children_by_type(self, node: Any, node_type: str) -> List[Any]:
        """Find all children of specified type."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return []
        return [node.child(i) for i in range(node.child_count)
                if node.child(i) and node.child(i).type == node_type]

    def get_node_line_range(self, node: Any) -> tuple:
        """Get (start_line, end_line) 1-based."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return (1, 1)
        return (node.start_point[0] + 1, node.end_point[0] + 1)

    def get_node_byte_range(self, node: Any) -> tuple:
        """Get (start_byte, end_byte)."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return (0, 0)
        return (node.start_byte, node.end_byte)

    def walk_tree(self, node: Any) -> Iterator[Any]:
        """Walk all nodes depth-first."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return
        yield node
        for i in range(node.child_count):
            child = node.child(i)
            if child:
                yield from self.walk_tree(child)

    def get_fallback_name(self, node: Any, prefix: str) -> str:
        """Generate fallback name based on line number."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return f"{prefix}_unknown"
        line_num = node.start_point[0] + 1 if hasattr(node, "start_point") else 0
        return f"{prefix}_{line_num}"

    def clean_comment_text(self, text: str) -> str:
        """Remove comment markers from text."""
        cleaned = text.strip()
        if cleaned.startswith("//"):
            cleaned = cleaned[2:].strip()
        elif cleaned.startswith("#"):
            cleaned = cleaned[1:].strip()
        elif cleaned.startswith("--"):
            cleaned = cleaned[2:].strip()
        if cleaned.startswith("/*") and cleaned.endswith("*/"):
            cleaned = cleaned[2:-2].strip()
        return cleaned

    def get_expression_preview(self, expr: str, max_length: int = 20) -> str:
        """Get truncated expression for naming."""
        if not expr:
            return "expr"
        expr = expr.replace('"', "").replace("'", "").replace(" ", "_")
        if len(expr) > max_length:
            expr = expr[:max_length - 3] + "..."
        return expr if expr else "expr"

    def find_child_by_type(self, node: Any, node_type: str) -> Optional[Any]:
        """Find first child of specified type."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return None
        for i in range(node.child_count):
            child = node.child(i)
            if child and child.type == node_type:
                return child
        return None

    def find_children_by_type(self, node: Any, node_type: str) -> List[Any]:
        """Find all children of specified type."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return []
        return [node.child(i) for i in range(node.child_count) 
                if node.child(i) and node.child(i).type == node_type]

    def get_node_line_range(self, node: Any) -> tuple:
        """Get (start_line, end_line) 1-based."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return (1, 1)
        return (node.start_point[0] + 1, node.end_point[0] + 1)

    def get_node_byte_range(self, node: Any) -> tuple:
        """Get (start_byte, end_byte)."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return (0, 0)
        return (node.start_byte, node.end_byte)

    def walk_tree(self, node: Any) -> Iterator[Any]:
        """Walk all nodes depth-first."""
        if not TREE_SITTER_AVAILABLE or node is None:
            return
        yield node
        for i in range(node.child_count):
            child = node.child(i)
            if child:
                yield from self.walk_tree(child)

