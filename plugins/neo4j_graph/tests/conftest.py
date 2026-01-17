# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""Pytest fixtures for Neo4j plugin tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

# Add plugin root to path for standalone test runs
_PLUGIN_ROOT = Path(__file__).parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))


def pytest_configure(config):
    """Register markers."""
    config.addinivalue_line("markers", "neo4j: requires live Neo4j")


@pytest.fixture
def clean_env() -> Generator[dict, None, None]:
    """Clean environment, restore after test."""
    original = os.environ.copy()
    yield os.environ
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture
def neo4j_env(clean_env) -> dict:
    """Environment configured for Neo4j."""
    clean_env["NEO4J_GRAPH"] = "1"
    clean_env["NEO4J_URI"] = "bolt://localhost:7687"
    clean_env["NEO4J_USER"] = "neo4j"
    clean_env["NEO4J_PASSWORD"] = "testpassword"
    return clean_env


@pytest.fixture
def mock_neo4j_driver():
    """Mock Neo4j driver."""
    with patch("neo4j.GraphDatabase") as mock_gdb:
        driver = MagicMock()
        mock_gdb.driver.return_value = driver
        
        session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        result = MagicMock()
        result.single.return_value = {"cnt": 1}
        result.__iter__ = lambda self: iter([])
        session.run.return_value = result
        
        yield driver


@pytest.fixture
def sample_edges():
    """Sample edges for testing."""
    from base import GraphEdge
    
    return [
        GraphEdge(
            id="e1",
            caller_symbol="main",
            callee_symbol="helper",
            caller_path="src/main.py",
            edge_type="calls",
            repo="test",
            start_line=10,
            language="python",
        ),
        GraphEdge(
            id="e2",
            caller_symbol="main",
            callee_symbol="os",
            caller_path="src/main.py",
            edge_type="imports",
            repo="test",
            language="python",
        ),
    ]

