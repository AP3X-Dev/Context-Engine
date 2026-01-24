"""Shared extraction utilities for language mappings."""

from scripts.ingest.language_mappings._shared.js_family_extraction import JSFamilyExtraction
from scripts.ingest.language_mappings._shared.js_query_patterns import (
    COMMONJS_EXPORTS_SHORTHAND,
    COMMONJS_MODULE_EXPORTS,
    COMMONJS_NESTED_EXPORTS,
    LEXICAL_DECLARATION_CONFIG,
    VAR_DECLARATION_CONFIG,
)

__all__ = [
    "JSFamilyExtraction",
    "LEXICAL_DECLARATION_CONFIG",
    "VAR_DECLARATION_CONFIG",
    "COMMONJS_MODULE_EXPORTS",
    "COMMONJS_NESTED_EXPORTS",
    "COMMONJS_EXPORTS_SHORTHAND",
]

