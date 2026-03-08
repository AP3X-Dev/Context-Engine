"""
MCP Tenant Router — pure utility functions for scoping collection names
to individual tenants in the ONI Cortex multi-tenant retrieval service.

Naming convention: {tenant_id}_{collection_name}
"""

from __future__ import annotations

import copy


def scope_collection_name(tenant_id: str, collection_name: str) -> str:
    """Return the tenant-scoped collection name.

    >>> scope_collection_name("abc123", "codebase")
    'abc123_codebase'
    """
    return f"{tenant_id}_{collection_name}"


def inject_tenant_context(
    tenant_id: str,
    tool_args: dict,
    default_collection: str = "default",
) -> dict:
    """Return a *copy* of *tool_args* with the ``collection`` value scoped to
    *tenant_id*.

    * If ``collection`` is missing or an empty string the *default_collection*
      (also tenant-prefixed) is used instead.
    * The original *tool_args* dict is never mutated.
    """
    scoped = copy.deepcopy(tool_args)
    collection = scoped.get("collection")
    if not collection:  # missing key, None, or empty string
        collection = default_collection
    scoped["collection"] = scope_collection_name(tenant_id, collection)
    return scoped


def strip_tenant_prefix(tenant_id: str, collection_name: str) -> str:
    """Remove the ``{tenant_id}_`` prefix from *collection_name* for display.

    If the prefix is not present the name is returned unchanged.
    """
    prefix = f"{tenant_id}_"
    if collection_name.startswith(prefix):
        return collection_name[len(prefix):]
    return collection_name
