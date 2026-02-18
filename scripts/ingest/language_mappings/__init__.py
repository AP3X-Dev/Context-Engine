"""Language-specific tree-sitter mappings for concept-based extraction.

This package contains base classes and language-specific implementations
for mapping tree-sitter AST nodes to semantic concepts (DEFINITION, BLOCK,
COMMENT, IMPORT, STRUCTURE) for intelligent chunking.
"""

from typing import Dict, List, Optional, Type

from .base import BaseMapping, ConceptType, ConceptResult
from .bash import BashMapping
from .c import CMapping
from .cpp import CppMapping
from .csharp import CSharpMapping
from .dart import DartMapping
from .go import GoMapping
from .groovy import GroovyMapping
from .haskell import HaskellMapping
from .hcl import HclMapping
from .java import JavaMapping
from .javascript import JavaScriptMapping
from .json import JsonMapping
from .jsx import JSXMapping
from .kotlin import KotlinMapping
from .lua import LuaMapping
from .makefile import MakefileMapping
from .markdown import MarkdownMapping
from .matlab import MatlabMapping
from .objc import ObjCMapping

from .pascal import PascalMapping
from .dfm import DfmMapping
from .php import PHPMapping
from .python import PythonMapping
from .rust import RustMapping
from .svelte import SvelteMapping
from .swift import SwiftMapping
from .text import TextMapping
from .toml import TomlMapping
from .tsx import TSXMapping
from .typescript import TypeScriptMapping
from .vue import VueMapping
from .vue_template import VueTemplateMapping
from .yaml import YamlMapping
from .zig import ZigMapping

# Language name -> Mapping class registry
_MAPPINGS: Dict[str, Type[BaseMapping]] = {
    "bash": BashMapping,
    "c": CMapping,
    "cpp": CppMapping,
    "csharp": CSharpMapping,
    "dart": DartMapping,
    "go": GoMapping,
    "groovy": GroovyMapping,
    "haskell": HaskellMapping,
    "hcl": HclMapping,
    "java": JavaMapping,
    "javascript": JavaScriptMapping,
    "json": JsonMapping,
    "jsx": JSXMapping,
    "kotlin": KotlinMapping,
    "lua": LuaMapping,
    "makefile": MakefileMapping,
    "markdown": MarkdownMapping,
    "matlab": MatlabMapping,
    "objc": ObjCMapping,

    "pascal": PascalMapping,
    "delphi": PascalMapping,   # Alias
    "dfm": DfmMapping,
    "php": PHPMapping,
    "python": PythonMapping,
    "rust": RustMapping,
    "svelte": SvelteMapping,
    "swift": SwiftMapping,
    "text": TextMapping,
    "toml": TomlMapping,
    "tsx": TSXMapping,
    "typescript": TypeScriptMapping,
    "vue": VueMapping,
    "vue_template": VueTemplateMapping,
    "yaml": YamlMapping,
    "zig": ZigMapping,
}


def get_mapping(language: str) -> Optional[BaseMapping]:
    """Get a mapping instance for the given language."""
    mapping_class = _MAPPINGS.get(language.lower())
    if mapping_class:
        return mapping_class()
    return None


def supported_languages() -> List[str]:
    """Get list of supported languages."""
    return list(_MAPPINGS.keys())


__all__ = [
    # Base classes
    "BaseMapping",
    "ConceptType",
    "ConceptResult",
    # Helper functions
    "get_mapping",
    "supported_languages",
    # Language mappings
    "BashMapping",
    "CMapping",
    "CppMapping",
    "CSharpMapping",
    "DartMapping",
    "GoMapping",
    "GroovyMapping",
    "HaskellMapping",
    "HclMapping",
    "JavaMapping",
    "JavaScriptMapping",
    "JsonMapping",
    "JSXMapping",
    "KotlinMapping",
    "LuaMapping",
    "MakefileMapping",
    "MarkdownMapping",
    "MatlabMapping",
    "ObjCMapping",

    "PascalMapping",
    "DfmMapping",
    "PHPMapping",
    "PythonMapping",
    "RustMapping",
    "SvelteMapping",
    "SwiftMapping",
    "TextMapping",
    "TomlMapping",
    "TSXMapping",
    "TypeScriptMapping",
    "VueMapping",
    "VueTemplateMapping",
    "YamlMapping",
    "ZigMapping",
]
