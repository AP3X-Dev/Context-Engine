#!/usr/bin/env python3
"""Verify import extraction across all supported languages."""
from scripts.ingest.metadata import _ts_extract_imports, _TS_IMPORT_CONFIG

print('Languages with tree-sitter import extraction:')
for lang in sorted(_TS_IMPORT_CONFIG.keys()):
    print(f'  - {lang}')

print(f'\nTotal: {len(_TS_IMPORT_CONFIG)} language configs')

# Quick verification for each language
tests = {
    'python': ('from pkg import Foo', ['pkg', 'Foo']),
    'javascript': ('import { Foo } from "pkg";', ['pkg', 'Foo']),
    'typescript': ('import { Foo } from "pkg";', ['pkg', 'Foo']),
    'go': ('import "github.com/pkg/foo"', ['github.com/pkg/foo', 'foo']),
    'rust': ('use std::collections::HashMap;', ['std::collections::HashMap', 'HashMap']),
    'java': ('import com.pkg.Foo;', ['com.pkg.Foo', 'Foo']),
    'c': ('#include <stdio.h>', ['stdio.h']),
    'cpp': ('#include <vector>', ['vector']),
    'csharp': ('using System.Text;', ['System.Text', 'Text']),
    'kotlin': ('import com.pkg.Foo', ['com.pkg.Foo', 'Foo']),
    'scala': ('import java.util.List', ['java.util.List', 'List']),
    'php': ('use Namespace\\Foo;', ['Namespace\\Foo']),
    'swift': ('import Foundation', ['Foundation']),
    'ruby': ('require "json"', ['json']),
}

print('\nVerification:')
all_pass = True
for lang, (code, expected) in tests.items():
    result = _ts_extract_imports(lang, code)
    missing = [e for e in expected if e not in result]
    if missing:
        print(f'  ❌ {lang}: missing {missing}, got {result}')
        all_pass = False
    else:
        display = f'{result[:3]}...' if len(result) > 3 else str(result)
        print(f'  ✅ {lang}: {display}')

print(f'\n{"All languages verified!" if all_pass else "Some issues found."}')

