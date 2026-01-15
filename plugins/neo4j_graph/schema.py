# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Neo4j Knowledge Graph Schema for Context-Engine.

Production-grade schema with:
- Rich node types (File, Module, Class, Function, Method, Interface, Concept)
- Semantic relationships (CALLS, IMPORTS, INHERITS_FROM, IMPLEMENTS, TESTS, etc.)
- Properties for embeddings, PageRank, community detection
- Indexes for fast traversal

This is the brain of the Graph RAG system.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Node Types
# =============================================================================

class NodeType(str, Enum):
    """Knowledge graph node types."""
    FILE = "File"
    MODULE = "Module"  # Package/namespace
    CLASS = "Class"
    INTERFACE = "Interface"
    FUNCTION = "Function"
    METHOD = "Method"
    VARIABLE = "Variable"
    CONSTANT = "Constant"
    CONCEPT = "Concept"  # Extracted from docstrings/comments
    TEST = "Test"
    REPO = "Repo"


# =============================================================================
# Relationship Types
# =============================================================================

class RelationType(str, Enum):
    """Knowledge graph relationship types."""
    # Code structure
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    INHERITS_FROM = "INHERITS_FROM"
    IMPLEMENTS = "IMPLEMENTS"
    OVERRIDES = "OVERRIDES"
    DECORATES = "DECORATES"
    
    # Containment
    CONTAINS = "CONTAINS"  # File/Module/Class contains symbols
    DEFINED_IN = "DEFINED_IN"  # Symbol defined in file
    BELONGS_TO = "BELONGS_TO"  # Symbol belongs to module/package
    
    # Testing
    TESTS = "TESTS"  # Test → function being tested
    TESTED_BY = "TESTED_BY"  # Inverse
    
    # Semantic
    SIMILAR_TO = "SIMILAR_TO"  # Semantic similarity
    RELATED_TO = "RELATED_TO"  # Concept relationship
    DOCUMENTS = "DOCUMENTS"  # Docstring → concept
    
    # Dependencies
    DEPENDS_ON = "DEPENDS_ON"  # Transitive dependency
    USED_BY = "USED_BY"  # Inverse


# =============================================================================
# Node Definitions
# =============================================================================

@dataclass
class GraphNode:
    """Base class for knowledge graph nodes."""
    id: str  # Unique identifier
    name: str
    node_type: NodeType
    repo: str
    path: Optional[str] = None  # File path
    
    # Code properties
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    language: Optional[str] = None
    signature: Optional[str] = None
    docstring: Optional[str] = None
    
    # Analysis properties
    complexity: int = 0
    decorators: List[str] = field(default_factory=list)
    
    # Graph RAG properties
    embedding: Optional[List[float]] = None  # Dense vector for similarity
    pagerank: float = 0.0
    community_id: Optional[int] = None
    importance_score: float = 0.0
    
    # Timestamps
    indexed_at: Optional[int] = None
    modified_at: Optional[int] = None
    
    def to_neo4j_props(self) -> Dict[str, Any]:
        """Convert to Neo4j properties dict (excludes None values)."""
        props = {
            "id": self.id,
            "name": self.name,
            "repo": self.repo,
        }
        if self.path:
            props["path"] = self.path
        if self.start_line is not None:
            props["start_line"] = self.start_line
        if self.end_line is not None:
            props["end_line"] = self.end_line
        if self.language:
            props["language"] = self.language
        if self.signature:
            props["signature"] = self.signature
        if self.docstring:
            # Truncate long docstrings
            props["docstring"] = self.docstring[:2000] if len(self.docstring) > 2000 else self.docstring
        if self.complexity > 0:
            props["complexity"] = self.complexity
        if self.decorators:
            props["decorators"] = self.decorators
        # Persist embeddings for semantic similarity (Neo4j supports vector indexes)
        if self.embedding is not None:
            props["embedding"] = self.embedding
        if self.pagerank > 0:
            props["pagerank"] = self.pagerank
        if self.community_id is not None:
            props["community_id"] = self.community_id
        if self.importance_score > 0:
            props["importance"] = self.importance_score
        if self.indexed_at:
            props["indexed_at"] = self.indexed_at
        if self.modified_at:
            props["modified_at"] = self.modified_at
        return props


@dataclass
class GraphRelationship:
    """Knowledge graph relationship."""
    source_id: str
    target_id: str
    rel_type: RelationType
    
    # Relationship properties
    weight: float = 1.0
    caller_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    repo: Optional[str] = None
    
    def to_neo4j_props(self) -> Dict[str, Any]:
        """Convert to Neo4j relationship properties."""
        props = {"weight": self.weight}
        if self.caller_path:
            props["caller_path"] = self.caller_path
        if self.start_line is not None:
            props["start_line"] = self.start_line
        if self.end_line is not None:
            props["end_line"] = self.end_line
        if self.repo:
            props["repo"] = self.repo
        return props

