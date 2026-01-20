# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""Tests for plugin interface."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add plugin root to path for standalone test runs
_PLUGIN_ROOT = Path(__file__).parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))


class TestPluginManifest:
    """Tests for PLUGIN_MANIFEST."""
    
    def test_manifest_fields(self):
        """Test manifest has required fields."""
        from plugin import PLUGIN_MANIFEST
        
        assert "name" in PLUGIN_MANIFEST
        assert "version" in PLUGIN_MANIFEST
        assert "capabilities" in PLUGIN_MANIFEST
        assert "type" in PLUGIN_MANIFEST
    
    def test_manifest_name(self):
        """Test plugin name format."""
        from plugin import PLUGIN_MANIFEST
        
        assert "neo4j" in PLUGIN_MANIFEST["name"].lower()
        assert "context-engine" in PLUGIN_MANIFEST["name"].lower()
    
    def test_manifest_type(self):
        """Test plugin type."""
        from plugin import PLUGIN_MANIFEST
        
        assert PLUGIN_MANIFEST["type"] == "graph_backend"


class TestRegisterPlugin:
    """Tests for register_plugin()."""
    
    def test_returns_manifest(self):
        """Test register_plugin returns PluginManifest."""
        from plugin import register_plugin, PluginManifest
        
        manifest = register_plugin(context_engine_version="1.0.0")
        
        assert isinstance(manifest, PluginManifest)
        assert manifest.name is not None
    
    def test_compatible_version(self):
        """Test compatible version."""
        from plugin import register_plugin
        
        manifest = register_plugin(context_engine_version="1.0.0")
        
        assert manifest.compatible is True
    
    def test_factory_functions(self):
        """Test factory functions are set."""
        from plugin import register_plugin
        
        manifest = register_plugin(context_engine_version="1.0.0")
        
        # These may be None if neo4j not installed
        assert manifest.get_mcp_tools is not None
        assert manifest.health_check is not None
    
    def test_capabilities_list(self):
        """Test capabilities are populated."""
        from plugin import register_plugin, PluginCapability
        
        manifest = register_plugin(context_engine_version="1.0.0")
        
        assert len(manifest.capabilities) > 0
        cap_names = [c.name for c in manifest.capabilities]
        assert "neo4j_backend" in cap_names
        assert "knowledge_graph" in cap_names


class TestHealthCheck:
    """Tests for health check."""
    
    def test_health_check_structure(self):
        """Test health check returns proper structure."""
        from plugin import register_plugin
        
        manifest = register_plugin(context_engine_version="1.0.0")
        health = manifest.health_check()
        
        assert "plugin" in health
        assert "version" in health
        assert "healthy" in health
        assert "checks" in health
    
    def test_health_check_driver(self):
        """Test health check includes driver check."""
        from plugin import register_plugin
        
        manifest = register_plugin(context_engine_version="1.0.0")
        health = manifest.health_check()
        
        assert "neo4j_driver" in health["checks"]


class TestMCPTools:
    """Tests for MCP tool registration."""
    
    def test_get_mcp_tools_returns_list(self):
        """Test get_mcp_tools returns list."""
        from plugin import register_plugin
        
        manifest = register_plugin(context_engine_version="1.0.0")
        tools = manifest.get_mcp_tools()
        
        assert isinstance(tools, list)
    
    def test_tool_has_required_fields(self):
        """Test each tool has required fields."""
        from plugin import register_plugin
        
        manifest = register_plugin(context_engine_version="1.0.0")
        tools = manifest.get_mcp_tools()
        
        for tool in tools:
            assert "name" in tool
            assert "description" in tool

