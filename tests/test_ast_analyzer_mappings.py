#!/usr/bin/env python3
"""
Comprehensive tests for ast_analyzer language mappings integration.

Tests that:
1. All 32 language mappings can be instantiated
2. ast_analyzer correctly uses mappings for symbol extraction
3. Import extraction works across languages
4. Call extraction works
5. Fallback to legacy analyzers works when needed
"""

import pytest
from scripts.ast_analyzer import (
    get_ast_analyzer,
    ASTAnalyzer,
    CodeSymbol,
    ConceptUnit,
    ImportReference,
    CallReference,
    _LANGUAGE_MAPPINGS_AVAILABLE,
    _TS_AVAILABLE,
)
from scripts.ingest.language_mappings import _MAPPINGS, get_mapping, ConceptType


# =============================================================================
# Test: All Language Mappings Instantiate
# =============================================================================

class TestLanguageMappingsComplete:
    """Verify all 35 language mappings can be instantiated."""

    def test_all_mappings_instantiate(self):
        """Every registered mapping class should instantiate without error."""
        failed = []
        passed = []

        for lang, mapping_class in _MAPPINGS.items():
            try:
                instance = mapping_class()
                assert instance is not None
                assert hasattr(instance, 'get_query_for_concept')
                passed.append(lang)
            except Exception as e:
                failed.append((lang, str(e)))

        assert len(failed) == 0, f"Failed mappings: {failed}"
        assert len(passed) == 35, f"Expected 35 mappings, got {len(passed)}"

    def test_all_mappings_have_definition_query(self):
        """All mappings should provide a DEFINITION query."""
        missing = []
        for lang, mapping_class in _MAPPINGS.items():
            try:
                instance = mapping_class()
                query = instance.get_query_for_concept(ConceptType.DEFINITION)
                if query is None:
                    missing.append(lang)
            except Exception:
                pass  # Tested separately

        # Some mappings (text, markdown) may not have DEFINITION queries
        assert len(missing) <= 5, f"Too many missing DEFINITION queries: {missing}"


# =============================================================================
# Test: Python Analysis
# =============================================================================

class TestPythonAnalysis:
    """Test Python code analysis via mappings."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    def test_python_function_extraction(self, analyzer):
        """Extract Python functions."""
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello {name}"

async def async_hello():
    pass
'''
        result = analyzer.analyze_file('/test.py', 'python', code)
        symbols = result.get('symbols', [])
        
        names = [s.name for s in symbols]
        assert 'hello' in names
        assert 'async_hello' in names

    def test_python_class_extraction(self, analyzer):
        """Extract Python classes and methods."""
        code = '''
class MyClass:
    """A test class."""
    
    def __init__(self, value):
        self.value = value
    
    def get_value(self):
        return self.value
'''
        result = analyzer.analyze_file('/test.py', 'python', code)
        symbols = result.get('symbols', [])
        
        names = [s.name for s in symbols]
        assert 'MyClass' in names
        
        kinds = {s.name: s.kind for s in symbols}
        assert kinds.get('MyClass') == 'class'

    def test_python_imports(self, analyzer):
        """Extract Python imports."""
        code = '''
import os
import sys
from pathlib import Path
from typing import List, Dict
'''
        result = analyzer.analyze_file('/test.py', 'python', code)
        imports = result.get('imports', [])
        
        modules = [i.module for i in imports]
        assert 'os' in modules
        assert 'sys' in modules
        assert 'pathlib' in modules
        assert 'typing' in modules

    def test_python_calls(self, analyzer):
        """Extract Python function calls."""
        code = '''
def main():
    print("Hello")
    os.path.join("a", "b")
    helper()

def helper():
    pass
'''
        result = analyzer.analyze_file('/test.py', 'python', code)
        calls = result.get('calls', [])
        
        callees = [c.callee for c in calls]
        assert 'print' in callees


# =============================================================================
# Test: JavaScript/TypeScript Analysis
# =============================================================================

class TestJavaScriptAnalysis:
    """Test JavaScript/TypeScript analysis via mappings."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_javascript_functions(self, analyzer):
        """Extract JavaScript functions."""
        code = '''
function greet(name) {
    console.log("Hello " + name);
}

const arrow = () => {
    return 42;
};
'''
        result = analyzer.analyze_file('/test.js', 'javascript', code)
        symbols = result.get('symbols', [])
        
        names = [s.name for s in symbols]
        assert 'greet' in names

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_typescript_imports(self, analyzer):
        """Extract TypeScript imports."""
        code = '''
import { useState, useEffect } from "react";
import axios from "axios";
import * as fs from "fs";
'''
        result = analyzer.analyze_file('/test.ts', 'typescript', code)
        imports = result.get('imports', [])
        
        modules = [i.module for i in imports]
        assert 'react' in modules
        assert 'axios' in modules
        assert 'fs' in modules


# =============================================================================
# Test: Go Analysis
# =============================================================================

class TestGoAnalysis:
    """Test Go analysis via mappings."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_go_functions(self, analyzer):
        """Extract Go functions."""
        code = '''
package main

func main() {
    fmt.Println("Hello")
}

func helper(x int) int {
    return x * 2
}
'''
        result = analyzer.analyze_file('/test.go', 'go', code)
        symbols = result.get('symbols', [])
        
        names = [s.name for s in symbols]
        assert 'main' in names
        assert 'helper' in names

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_go_imports(self, analyzer):
        """Extract Go imports."""
        code = '''
package main

import (
    "fmt"
    "os"
    "strings"
)

func main() {}
'''
        result = analyzer.analyze_file('/test.go', 'go', code)
        imports = result.get('imports', [])
        
        modules = [i.module for i in imports]
        assert 'fmt' in modules
        assert 'os' in modules
        assert 'strings' in modules


# =============================================================================
# Test: Rust Analysis
# =============================================================================

class TestRustAnalysis:
    """Test Rust analysis via mappings."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_rust_functions(self, analyzer):
        """Extract Rust functions."""
        code = '''
fn main() {
    println!("Hello");
}

pub fn helper(x: i32) -> i32 {
    x * 2
}
'''
        result = analyzer.analyze_file('/test.rs', 'rust', code)
        symbols = result.get('symbols', [])
        
        names = [s.name for s in symbols]
        assert 'main' in names
        assert 'helper' in names

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_rust_imports(self, analyzer):
        """Extract Rust use statements."""
        code = '''
use std::io;
use std::collections::HashMap;

fn main() {}
'''
        result = analyzer.analyze_file('/test.rs', 'rust', code)
        imports = result.get('imports', [])
        
        modules = [i.module for i in imports]
        assert any('std' in m for m in modules)


# =============================================================================
# Test: Java Analysis
# =============================================================================

class TestJavaAnalysis:
    """Test Java analysis via mappings."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_java_class(self, analyzer):
        """Extract Java class and methods."""
        code = '''
public class Hello {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
    
    private int helper(int x) {
        return x * 2;
    }
}
'''
        result = analyzer.analyze_file('/Hello.java', 'java', code)
        symbols = result.get('symbols', [])
        
        names = [s.name for s in symbols]
        assert 'Hello' in names
        assert 'main' in names

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_java_imports(self, analyzer):
        """Extract Java imports."""
        code = '''
import java.util.List;
import java.util.ArrayList;
import java.io.*;

public class Test {}
'''
        result = analyzer.analyze_file('/Test.java', 'java', code)
        imports = result.get('imports', [])
        
        modules = [i.module for i in imports]
        assert 'java.util.List' in modules
        assert 'java.util.ArrayList' in modules


# =============================================================================
# Test: C/C++ Analysis
# =============================================================================

class TestCppAnalysis:
    """Test C/C++ analysis via mappings."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_cpp_functions(self, analyzer):
        """Extract C++ functions."""
        code = '''
#include <iostream>

int main() {
    std::cout << "Hello" << std::endl;
    return 0;
}

int helper(int x) {
    return x * 2;
}
'''
        result = analyzer.analyze_file('/test.cpp', 'cpp', code)
        symbols = result.get('symbols', [])
        
        names = [s.name for s in symbols]
        assert 'main' in names

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_cpp_includes(self, analyzer):
        """Extract C++ includes."""
        code = '''
#include <iostream>
#include <vector>
#include "myheader.h"

int main() { return 0; }
'''
        result = analyzer.analyze_file('/test.cpp', 'cpp', code)
        imports = result.get('imports', [])
        
        modules = [i.module for i in imports]
        assert 'iostream' in modules
        assert 'vector' in modules


# =============================================================================
# Test: Multi-Language Consistency
# =============================================================================

class TestMultiLanguageConsistency:
    """Test that analysis is consistent across languages."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_all_return_correct_types(self, analyzer):
        """All analyses should return correct types."""
        test_cases = [
            ('python', 'def foo(): pass'),
            ('javascript', 'function foo() {}'),
            ('go', 'package main\nfunc foo() {}'),
            ('rust', 'fn foo() {}'),
            ('java', 'public class Foo {}'),
            ('cpp', 'int foo() { return 0; }'),
        ]
        
        for lang, code in test_cases:
            result = analyzer.analyze_file(f'/test.{lang}', lang, code)
            
            assert isinstance(result, dict), f"{lang}: result should be dict"
            assert 'symbols' in result, f"{lang}: should have symbols"
            assert 'imports' in result, f"{lang}: should have imports"
            assert 'calls' in result, f"{lang}: should have calls"
            
            for sym in result.get('symbols', []):
                assert isinstance(sym, CodeSymbol), f"{lang}: symbols should be CodeSymbol"
            for imp in result.get('imports', []):
                assert isinstance(imp, ImportReference), f"{lang}: imports should be ImportReference"
            for call in result.get('calls', []):
                assert isinstance(call, CallReference), f"{lang}: calls should be CallReference"

    @pytest.mark.skipif(not _TS_AVAILABLE, reason="tree-sitter not available")
    def test_empty_file_handling(self, analyzer):
        """Empty files should not crash."""
        for lang in ['python', 'javascript', 'go', 'rust', 'java']:
            result = analyzer.analyze_file(f'/empty.{lang}', lang, '')
            assert isinstance(result, dict)
            
            result = analyzer.analyze_file(f'/whitespace.{lang}', lang, '   \n\n   ')
            assert isinstance(result, dict)


# =============================================================================
# Test: Fallback Behavior
# =============================================================================

class TestFallbackBehavior:
    """Test fallback to legacy analyzers."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    def test_unsupported_language_fallback(self, analyzer):
        """Unsupported languages should fall back gracefully."""
        code = 'some unknown code here'
        result = analyzer.analyze_file('/test.xyz', 'unknown_language', code)
        
        # Should return empty analysis, not crash
        assert isinstance(result, dict)
        assert 'symbols' in result
        assert 'imports' in result

    def test_syntax_error_handling(self, analyzer):
        """Syntax errors should be handled gracefully."""
        # Malformed Python
        code = 'def foo(\n  broken syntax here'
        result = analyzer.analyze_file('/test.py', 'python', code)
        
        # Should not crash
        assert isinstance(result, dict)


# =============================================================================
# Test: Symbol Metadata
# =============================================================================

class TestSymbolMetadata:
    """Test that symbol metadata is extracted correctly."""

    @pytest.fixture
    def analyzer(self):
        return get_ast_analyzer(reset=True)

    def test_python_symbol_metadata(self, analyzer):
        """Python symbols should have rich metadata."""
        code = '''
@decorator
def my_function(a: int, b: str) -> bool:
    """This is the docstring."""
    return True
'''
        result = analyzer.analyze_file('/test.py', 'python', code)
        symbols = result.get('symbols', [])
        
        func = next((s for s in symbols if s.name == 'my_function'), None)
        assert func is not None
        assert func.kind == 'function'
        assert func.start_line > 0
        assert func.end_line >= func.start_line

    def test_symbol_line_numbers(self, analyzer):
        """Symbol line numbers should be accurate."""
        code = '''# Line 1
# Line 2
def foo():  # Line 3
    pass    # Line 4
# Line 5
def bar():  # Line 6
    pass    # Line 7
'''
        result = analyzer.analyze_file('/test.py', 'python', code)
        symbols = result.get('symbols', [])
        
        foo = next((s for s in symbols if s.name == 'foo'), None)
        bar = next((s for s in symbols if s.name == 'bar'), None)
        
        assert foo is not None
        assert bar is not None
        assert foo.start_line == 3
        assert bar.start_line == 6


# =============================================================================
# Run tests
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
