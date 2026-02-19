# Delphi/Pascal Support for Context-Engine

## Summary

This PR adds full support for **Delphi/Pascal** source files and **DFM/FMX form files** to the Context-Engine. The implementation follows the existing `language_mappings` system and integrates seamlessly into the current architecture.

### About Delphi/Pascal

[Delphi](https://www.embarcadero.com/products/delphi) is a commercial IDE and compiler for Object Pascal, widely used for building native Windows desktop applications, cross-platform mobile apps (via FireMonkey), and server-side systems. It has a large legacy codebase footprint, particularly in enterprise and industrial environments.

Key characteristics relevant to indexing:
- **`.pas` units** contain Object Pascal source code with a distinctive `interface`/`implementation` section structure and `uses` clauses for dependency management.
- **`.dfm`/`.fmx` form files** are Delphi-specific declarative files that describe UI layouts (component trees, properties, and event handler bindings). They are not code but have strong cross-references into `.pas` units.
- **`.dpr`/`.dpk` project files** are Pascal source files that define the entry point for applications and packages respectively.
- **`.lpr` project files** are the [Lazarus](https://www.lazarus-ide.org/) (Free Pascal) equivalent of `.dpr` files, used by the open-source Lazarus IDE.

**Scope:** 11 files changed, ~1700 lines added, of which ~940 are tests.

---

## What Was Implemented?

### 1. File Detection (`config.py`)

New file extensions registered in `CODE_EXTS`:

| Extension | Language | Description |
|-----------|----------|-------------|
| `.pas` | `pascal` | Delphi/Lazarus unit |
| `.dpr` | `pascal` | Delphi project file |
| `.dpk` | `pascal` | Delphi package file |
| `.lpr` | `pascal` | Lazarus project file |
| `.dfm` | `dfm` | VCL form file |
| `.fmx` | `dfm` | FireMonkey form file |

Additional exclusions for Delphi-specific artifacts:
- Directories: `__history`, `__recovery` (Delphi IDE backups)
- Files: `*.dcu`, `*.dcp`, `*.dcpil` (compiled binaries)

### 2. PascalMapping (`language_mappings/pascal.py`)

Full language mapping for Pascal/Delphi using a **dual approach**:

- **Tree-sitter queries** (when `tree_sitter_pascal` is installed) for AST nodes: `declProc`, `declClass`, `declIntf`, `declEnum`, `declType`, `declConst`, `defProc`
- **Regex fallback** (always available) as the primary implementation

Extracted concepts:

| Concept | Example | Metadata Kind |
|---------|---------|---------------|
| Classes | `TMyClass = class(TBase)` | `class` |
| Records | `TPoint = record` | `record` |
| Interfaces | `ILogger = interface` | `interface` |
| Enumerations | `TStatus = (stNew, stActive)` | `enum` |
| Procedures/Functions | `procedure Execute;` | `function` |
| Methods | `procedure TMyClass.Execute;` | `method` |
| Constants | `const MAX = 100;` | `constant` |
| Type aliases | `TStringList = TList<string>;` | `type_alias` |
| Uses clauses | `uses System.SysUtils;` | `import` |

**Built-in filter:** RTL/VCL/FMX standard units (System, SysUtils, Classes, etc.) are recognized as built-ins to prevent false cross-references.

### 3. DfmMapping (`language_mappings/dfm.py`)

Standalone mapping for DFM/FMX form files — purely regex-based (no tree-sitter needed):

- Detects component declarations (`object ButtonLogin: TButton`)
- Detects nested components with hierarchy tracking
- Extracts event handler bindings (`OnClick = ButtonLoginClick`) as cross-file references
- Handles `inherited` forms correctly
- Skips multiline properties and item collections

### 4. Import Extraction (`metadata.py`)

Pascal `uses` clauses are correctly extracted — both single-line and multi-line:

```pascal
uses
  System.SysUtils,
  System.Classes,
  UAuth;
```

Keywords like `uses`, `in`, `interface`, `implementation` are filtered out.

### 5. Symbol Extraction (`symbols.py`)

`_extract_symbols_pascal()` extracts all symbol types with correct `kind`, `name`, and `path` (e.g., `TMyClass.Execute` for methods).

### 6. Tree-sitter Integration (`tree_sitter.py`)

`tree_sitter_pascal` has been added as an optional entry in the language loader. Since loading is wrapped in `try/except`, it gracefully falls back to the regex implementation when no Python package is installed.

### 7. Language Registry (`language_mappings/__init__.py`)

Three new entries:
- `"pascal"` → `PascalMapping`
- `"delphi"` → `PascalMapping` (alias)
- `"dfm"` → `DfmMapping`

---

## Design Decisions

### Why a Dual Approach (Regex + Optional Tree-sitter)?

There is no official `tree_sitter_pascal` Python package on PyPI compatible with the 0.25+ API. The regex fallback therefore serves as the primary implementation. Once a compatible package becomes available, the tree-sitter integration will activate automatically — without any code changes.

### Why Separate Mappings for `.pas` and `.dfm`?

DFM/FMX files have a completely different format from Pascal code (property declarations rather than a programming language). A separate `DfmMapping` with its own `"dfm"` language key is cleaner than mixing everything into `PascalMapping`.

### Reference: Codegraph

The Delphi support in Codegraph (TypeScript/web-tree-sitter) served as the reference implementation for AST node types, built-in filters, and DFM parsing.

---

## Tests

**~120 new tests** across four test files:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_pascal_language_mapping.py` | 47 | PascalMapping: instantiation, queries, import extraction, symbol extraction, metadata, realistic fixtures |
| `test_dfm_language_mapping.py` | ~30 | DfmMapping: instantiation, components, events, hierarchy, multiline properties, collections |
| `test_language_coverage.py` | 7 | Integration: Pascal uses-imports, Delphi alias, symbol coverage |
| `test_ast_analyzer_mappings.py` | 1 | Mapping count updated from 32 → 35 |

All tests pass (`1197 passed`).

---

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `scripts/ingest/config.py` | Modified | +6 extensions, +5 exclusions |
| `scripts/ingest/language_mappings/pascal.py` | **New** | PascalMapping (~400 lines) |
| `scripts/ingest/language_mappings/dfm.py` | **New** | DfmMapping (~220 lines) |
| `scripts/ingest/language_mappings/__init__.py` | Modified | +3 registry entries |
| `scripts/ingest/metadata.py` | Modified | +Pascal uses-clause extraction |
| `scripts/ingest/symbols.py` | Modified | +`_extract_symbols_pascal()` |
| `scripts/ingest/tree_sitter.py` | Modified | +optional `tree_sitter_pascal` entry |
| `tests/test_pascal_language_mapping.py` | **New** | 47 unit tests |
| `tests/test_dfm_language_mapping.py` | **New** | DFM tests |
| `tests/test_language_coverage.py` | Modified | +Pascal integration tests |
| `tests/test_ast_analyzer_mappings.py` | Modified | Mapping count updated |
