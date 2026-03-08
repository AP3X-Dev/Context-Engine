"""Tests for tenant-scoped collection resolution in MCP indexer."""

import os
import pytest


def test_resolve_collection_with_prefix():
    """When CORTEX_COLLECTION_PREFIX is set, collection name is prefixed."""
    os.environ["CORTEX_COLLECTION_PREFIX"] = "tenant123_"
    try:
        from scripts.mcp_indexer_server import _resolve_collection
        result = _resolve_collection("codebase")
        assert result == "tenant123_codebase"
    finally:
        del os.environ["CORTEX_COLLECTION_PREFIX"]


def test_resolve_collection_without_prefix():
    """Without prefix, returns base collection (backwards compatible)."""
    os.environ.pop("CORTEX_COLLECTION_PREFIX", None)
    os.environ["COLLECTION_NAME"] = "my_collection"
    try:
        from scripts.mcp_indexer_server import _resolve_collection
        result = _resolve_collection()
        assert result == "my_collection"
    finally:
        os.environ.pop("COLLECTION_NAME", None)


def test_resolve_collection_no_double_prefix():
    """If collection already has prefix, don't double-prefix."""
    os.environ["CORTEX_COLLECTION_PREFIX"] = "t1_"
    try:
        from scripts.mcp_indexer_server import _resolve_collection
        result = _resolve_collection("t1_codebase")
        assert result == "t1_codebase"
    finally:
        del os.environ["CORTEX_COLLECTION_PREFIX"]


def test_resolve_collection_empty_uses_default():
    """Empty collection arg uses COLLECTION_NAME env var."""
    os.environ.pop("CORTEX_COLLECTION_PREFIX", None)
    os.environ["COLLECTION_NAME"] = "default_coll"
    try:
        from scripts.mcp_indexer_server import _resolve_collection
        result = _resolve_collection("")
        assert result == "default_coll"
    finally:
        os.environ.pop("COLLECTION_NAME", None)
