"""Tests for the MCP tenant router collection-scoping utilities."""

from __future__ import annotations

import sys, os

# Ensure the project root is on sys.path so ``scripts.cortex`` is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.cortex.mcp_proxy import (
    inject_tenant_context,
    scope_collection_name,
    strip_tenant_prefix,
)


# --- scope_collection_name ---------------------------------------------------

def test_scope_collection_name():
    assert scope_collection_name("abc123", "codebase") == "abc123_codebase"


# --- inject_tenant_context ----------------------------------------------------

def test_inject_tenant_context_with_collection():
    args = {"collection": "codebase", "query": "hello"}
    result = inject_tenant_context("abc123", args)
    assert result["collection"] == "abc123_codebase"
    assert result["query"] == "hello"
    # Original must not be mutated.
    assert args["collection"] == "codebase"


def test_inject_tenant_context_without_collection():
    args = {"query": "hello"}
    result = inject_tenant_context("abc123", args)
    assert result["collection"] == "abc123_default"
    assert result["query"] == "hello"


def test_inject_tenant_context_empty_collection():
    args = {"collection": "", "query": "hello"}
    result = inject_tenant_context("abc123", args)
    assert result["collection"] == "abc123_default"
    assert result["query"] == "hello"


# --- strip_tenant_prefix ------------------------------------------------------

def test_strip_tenant_prefix():
    assert strip_tenant_prefix("abc123", "abc123_codebase") == "codebase"


def test_strip_tenant_prefix_no_match():
    assert strip_tenant_prefix("abc123", "other_codebase") == "other_codebase"
