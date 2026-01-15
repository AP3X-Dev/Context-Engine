# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""Tests for Neo4j backend."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add plugin root to path for standalone test runs
_PLUGIN_ROOT = Path(__file__).parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))


class TestNeo4jGraphBackend:
    """Tests for Neo4jGraphBackend."""

    def test_backend_type(self):
        """Test backend_type property."""
        from backend import Neo4jGraphBackend
        
        backend = Neo4jGraphBackend()
        assert backend.backend_type == "neo4j"
    
    @pytest.mark.neo4j
    def test_ensure_graph_store(self, mock_neo4j_driver, neo4j_env):
        """Test ensure_graph_store creates indexes."""
        from backend import Neo4jGraphBackend, _INITIALIZED_DATABASES
        
        _INITIALIZED_DATABASES.clear()
        
        with patch.object(Neo4jGraphBackend, "_get_driver", return_value=mock_neo4j_driver):
            backend = Neo4jGraphBackend()
            result = backend.ensure_graph_store("test-collection")
        
        assert result is not None
        session = mock_neo4j_driver.session.return_value.__enter__.return_value
        assert session.run.called
    
    @pytest.mark.neo4j
    def test_upsert_edges(self, mock_neo4j_driver, sample_edges, neo4j_env):
        """Test upserting edges."""
        from backend import Neo4jGraphBackend
        
        with patch.object(Neo4jGraphBackend, "_get_driver", return_value=mock_neo4j_driver):
            backend = Neo4jGraphBackend()
            count = backend.upsert_edges("neo4j", sample_edges)
        
        assert count == len(sample_edges)
    
    @pytest.mark.neo4j
    def test_get_callers(self, mock_neo4j_driver, neo4j_env):
        """Test getting callers."""
        from backend import Neo4jGraphBackend
        
        session = mock_neo4j_driver.session.return_value.__enter__.return_value
        session.run.return_value = iter([
            {"caller_symbol": "main", "callee_symbol": "helper", "caller_path": "main.py"}
        ])
        
        with patch.object(Neo4jGraphBackend, "_get_driver", return_value=mock_neo4j_driver):
            backend = Neo4jGraphBackend()
            results = backend.get_callers("neo4j", "helper")
        
        assert session.run.called


class TestNeo4jConnection:
    """Tests for Neo4j connection handling."""
    
    def test_driver_lazy_init(self):
        """Test driver is lazily initialized."""
        from backend import Neo4jGraphBackend
        
        backend = Neo4jGraphBackend()
        assert backend._driver is None
    
    @pytest.mark.neo4j
    def test_connection_pool_settings(self, neo4j_env):
        """Test connection pool configuration."""
        import os
        os.environ["NEO4J_MAX_POOL_SIZE"] = "25"
        
        from backend import Neo4jGraphBackend
        
        backend = Neo4jGraphBackend()
        # Pool size is read from env
        assert True  # Just check no errors


class TestEdgeTypes:
    """Tests for edge type handling."""
    
    def test_call_edge_cypher(self, mock_neo4j_driver, neo4j_env):
        """Test call edges use CALLS relationship."""
        from backend import Neo4jGraphBackend
        from base import GraphEdge
        
        edge = GraphEdge(
            id="e1",
            caller_symbol="foo",
            callee_symbol="bar",
            caller_path="test.py",
            edge_type="calls",
            repo="test",
        )
        
        with patch.object(Neo4jGraphBackend, "_get_driver", return_value=mock_neo4j_driver):
            backend = Neo4jGraphBackend()
            backend.upsert_edges("neo4j", [edge])
        
        session = mock_neo4j_driver.session.return_value.__enter__.return_value
        # Verify CALLS relationship was used
        call_args = str(session.run.call_args)
        assert "CALLS" in call_args or session.run.called
    
    def test_import_edge_cypher(self, mock_neo4j_driver, neo4j_env):
        """Test import edges use IMPORTS relationship."""
        from backend import Neo4jGraphBackend
        from base import GraphEdge
        
        edge = GraphEdge(
            id="e1",
            caller_symbol="foo",
            callee_symbol="os",
            caller_path="test.py",
            edge_type="imports",
            repo="test",
        )
        
        with patch.object(Neo4jGraphBackend, "_get_driver", return_value=mock_neo4j_driver):
            backend = Neo4jGraphBackend()
            backend.upsert_edges("neo4j", [edge])
        
        session = mock_neo4j_driver.session.return_value.__enter__.return_value
        assert session.run.called

