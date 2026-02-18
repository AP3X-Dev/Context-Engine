#!/usr/bin/env python3
"""
Comprehensive tests for PascalMapping — Delphi/Pascal language mapping.

Tests cover:
- PascalMapping instantiation and interface compliance
- Tree-sitter concept query strings
- Import extraction via the metadata pipeline
- Symbol extraction via the symbols pipeline
- Regex fallback extraction methods on PascalMapping itself
- Realistic Delphi .pas file fixtures (UAuth, UTypes)
"""

import pytest
from typing import List, Dict, Any

from scripts.ingest.language_mappings.pascal import (
    PascalMapping,
    PASCAL_BUILTIN_UNITS,
    PASCAL_BUILTIN_UNIT_PREFIXES,
    _classify_type_decl,
)
from scripts.ingest.language_mappings.base import ConceptType
from scripts.ingest.metadata import _extract_imports
from scripts.ingest.symbols import _extract_symbols_pascal


# =============================================================================
# Instantiation
# =============================================================================


class TestPascalMappingInstantiation:
    """PascalMapping instantiates correctly as a BaseMapping subclass."""

    def test_instantiate_without_error(self):
        """PascalMapping instantiates without error."""
        mapping = PascalMapping()
        assert mapping is not None

    def test_has_required_abstract_methods(self):
        """PascalMapping implements all BaseMapping abstract methods."""
        mapping = PascalMapping()
        assert callable(getattr(mapping, "get_query_for_concept"))
        assert callable(getattr(mapping, "extract_name"))
        assert callable(getattr(mapping, "extract_content"))
        assert callable(getattr(mapping, "extract_metadata"))

    def test_language_name(self):
        """Language name is 'pascal'."""
        mapping = PascalMapping()
        assert mapping.language == "pascal"


# =============================================================================
# Concept Queries
# =============================================================================


class TestPascalConceptQueries:
    """PascalMapping returns correct tree-sitter queries for each ConceptType."""

    @pytest.fixture
    def mapping(self):
        return PascalMapping()

    def test_definition_query_not_none(self, mapping):
        """DEFINITION concept returns a non-None, non-empty query string."""
        query = mapping.get_query_for_concept(ConceptType.DEFINITION)
        assert query is not None
        assert isinstance(query, str)
        assert len(query.strip()) > 0

    def test_import_query_not_none(self, mapping):
        """IMPORT concept returns a non-None query string referencing declUses."""
        query = mapping.get_query_for_concept(ConceptType.IMPORT)
        assert query is not None
        assert isinstance(query, str)
        assert "declUses" in query

    def test_comment_query_not_none(self, mapping):
        """COMMENT concept returns a non-None query string."""
        query = mapping.get_query_for_concept(ConceptType.COMMENT)
        assert query is not None
        assert isinstance(query, str)
        assert len(query.strip()) > 0

    def test_structure_query_not_none(self, mapping):
        """STRUCTURE concept returns a non-None query string for module declarations."""
        query = mapping.get_query_for_concept(ConceptType.STRUCTURE)
        assert query is not None
        assert isinstance(query, str)
        assert "module" in query

    def test_block_query_is_none(self, mapping):
        """BLOCK concept returns None — not implemented for Pascal."""
        query = mapping.get_query_for_concept(ConceptType.BLOCK)
        assert query is None


# =============================================================================
# Import Extraction (via metadata._extract_imports)
# =============================================================================


class TestPascalImportExtraction:
    """Tests Pascal uses-clause extraction via scripts.ingest.metadata._extract_imports."""

    def test_simple_one_line_uses(self):
        """uses SysUtils; → ['SysUtils'] in the result."""
        code = "unit Test;\ninterface\nuses SysUtils;\nimplementation\nend."
        imports = _extract_imports("pascal", code)
        assert "SysUtils" in imports

    def test_multiline_uses(self):
        """Multi-line uses clause extracts all listed units."""
        code = (
            "unit Test;\ninterface\nuses\n"
            "  System.SysUtils,\n"
            "  System.Classes,\n"
            "  UAuth;\nimplementation\nend."
        )
        imports = _extract_imports("pascal", code)
        assert "System.SysUtils" in imports
        assert "System.Classes" in imports
        assert "UAuth" in imports

    def test_qualified_unit_names(self):
        """Qualified names like Vcl.Forms are extracted as full-qualified tokens."""
        code = (
            "unit Test;\ninterface\nuses\n"
            "  Vcl.Forms,\n  Vcl.Controls;\nimplementation\nend."
        )
        imports = _extract_imports("pascal", code)
        assert "Vcl.Forms" in imports
        assert "Vcl.Controls" in imports

    def test_uses_does_not_include_pascal_keywords(self):
        """Reserved words 'uses', 'interface', 'implementation' are NOT included."""
        code = "unit Test;\ninterface\nuses SysUtils;\nimplementation\nend."
        imports = _extract_imports("pascal", code)
        assert "uses" not in imports
        assert "interface" not in imports
        assert "implementation" not in imports
        assert "end" not in imports
        assert "unit" not in imports

    def test_empty_uses_clause(self):
        """Code without a uses clause yields an empty import list."""
        code = "unit Test;\ninterface\nimplementation\nend."
        imports = _extract_imports("pascal", code)
        assert len(imports) == 0

    def test_multiple_uses_clauses(self):
        """Units from both interface and implementation uses clauses are extracted."""
        code = (
            "unit Test;\n"
            "interface\n"
            "uses UIntf;\n"
            "implementation\n"
            "uses UImpl;\n"
            "end."
        )
        imports = _extract_imports("pascal", code)
        assert "UIntf" in imports
        assert "UImpl" in imports

    def test_delphi_alias_extracts_same(self):
        """'delphi' language alias also routes to the Pascal uses-clause extractor."""
        code = "unit Test;\ninterface\nuses SysUtils;\nimplementation\nend."
        imports = _extract_imports("delphi", code)
        assert "SysUtils" in imports


# =============================================================================
# Symbol Extraction (via symbols._extract_symbols_pascal)
# =============================================================================


class TestPascalSymbolExtraction:
    """Tests Pascal symbol extraction via scripts.ingest.symbols._extract_symbols_pascal."""

    def test_class_extraction(self):
        """TMyClass = class is extracted with kind='class'."""
        code = "type\n  TMyClass = class\n  end;"
        syms = _extract_symbols_pascal(code)
        names_kinds = {s["name"]: s["kind"] for s in syms}
        assert "TMyClass" in names_kinds
        assert names_kinds["TMyClass"] == "class"

    def test_record_extraction(self):
        """TPoint = record is extracted (records use kind='class')."""
        code = "type\n  TPoint = record\n    X, Y: Double;\n  end;"
        syms = _extract_symbols_pascal(code)
        names = [s["name"] for s in syms]
        assert "TPoint" in names

    def test_interface_extraction(self):
        """ILogger = interface is extracted with kind='interface'."""
        code = "type\n  ILogger = interface\n  end;"
        syms = _extract_symbols_pascal(code)
        names_kinds = {s["name"]: s["kind"] for s in syms}
        assert "ILogger" in names_kinds
        assert names_kinds["ILogger"] == "interface"

    def test_procedure_extraction(self):
        """Standalone procedure is extracted as a function symbol."""
        code = "procedure ProcessData;\nbegin\nend;"
        syms = _extract_symbols_pascal(code)
        names = [s["name"] for s in syms]
        assert "ProcessData" in names

    def test_function_extraction(self):
        """Standalone function with parameters is extracted."""
        code = "function GetValue(const AParam: string);\nbegin\nend;"
        syms = _extract_symbols_pascal(code)
        names = [s["name"] for s in syms]
        assert "GetValue" in names

    def test_class_method_extraction(self):
        """TMyClass.DoWork method is extracted with kind='method'."""
        code = "procedure TMyClass.DoWork;\nbegin\nend;"
        syms = _extract_symbols_pascal(code)
        names_kinds = {s["name"]: s["kind"] for s in syms}
        assert "DoWork" in names_kinds
        assert names_kinds["DoWork"] == "method"

    def test_constructor_extraction(self):
        """TMyClass.Create constructor is extracted."""
        code = "constructor TMyClass.Create(const AValue: string);\nbegin\nend;"
        syms = _extract_symbols_pascal(code)
        names = [s["name"] for s in syms]
        assert "Create" in names

    def test_destructor_extraction(self):
        """TMyClass.Destroy destructor is extracted."""
        code = "destructor TMyClass.Destroy;\nbegin\nend;"
        syms = _extract_symbols_pascal(code)
        names = [s["name"] for s in syms]
        assert "Destroy" in names

    def test_constant_extraction(self):
        """UPPER_SNAKE_CASE constants are extracted with kind='constant'."""
        code = "const\n  MAX_RETRIES = 3;\n  APP_NAME = 'MyApp';"
        syms = _extract_symbols_pascal(code)
        names_kinds = {s["name"]: s["kind"] for s in syms}
        assert "MAX_RETRIES" in names_kinds
        assert names_kinds["MAX_RETRIES"] == "constant"

    def test_enum_extraction(self):
        """TColor = (clRed, clGreen) is extracted with kind='enum'."""
        code = "type\n  TColor = (clRed, clGreen, clBlue);"
        syms = _extract_symbols_pascal(code)
        names_kinds = {s["name"]: s["kind"] for s in syms}
        assert "TColor" in names_kinds
        assert names_kinds["TColor"] == "enum"


# =============================================================================
# PascalMapping extract_ and helper methods
# =============================================================================


class TestPascalMappingExtractMethods:
    """Tests PascalMapping.extract_name(), extract_content(), extract_metadata()
    and the import-module filtering helper."""

    @pytest.fixture
    def mapping(self):
        return PascalMapping()

    def test_extract_name_returns_string(self, mapping):
        """extract_name with empty captures returns a non-empty fallback string."""
        result = mapping.extract_name(ConceptType.DEFINITION, {}, b"code")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_extract_content_returns_string(self, mapping):
        """extract_content with empty captures returns a string (no node → empty)."""
        result = mapping.extract_content(ConceptType.DEFINITION, {}, b"code")
        assert isinstance(result, str)

    def test_extract_metadata_returns_dict(self, mapping):
        """extract_metadata with empty captures returns a dict (may be empty)."""
        result = mapping.extract_metadata(ConceptType.DEFINITION, {}, b"code")
        assert isinstance(result, dict)

    def test_metadata_has_kind_for_import_concept(self, mapping):
        """extract_metadata for IMPORT concept always returns kind='import'."""
        result = mapping.extract_metadata(ConceptType.IMPORT, {}, b"code")
        assert result.get("kind") == "import"

    def test_get_import_module_extracts_unit_name(self, mapping):
        """get_import_module returns the unit name for a user-defined unit."""
        result = mapping.get_import_module("UAuth")
        assert result == "UAuth"

    def test_builtin_units_filtered_by_name(self, mapping):
        """get_import_module returns None for exact built-in RTL unit names."""
        assert mapping.get_import_module("SysUtils") is None
        assert mapping.get_import_module("Classes") is None
        assert mapping.get_import_module("System") is None

    def test_builtin_units_filtered_by_prefix(self, mapping):
        """get_import_module returns None for qualified names with built-in prefixes."""
        assert mapping.get_import_module("System.SysUtils") is None
        assert mapping.get_import_module("Vcl.Forms") is None
        assert mapping.get_import_module("Fmx.Controls") is None

    def test_pascal_builtin_units_constant_content(self):
        """PASCAL_BUILTIN_UNITS contains well-known RTL unit names."""
        assert "SysUtils" in PASCAL_BUILTIN_UNITS
        assert "Classes" in PASCAL_BUILTIN_UNITS
        assert "System" in PASCAL_BUILTIN_UNITS
        assert "Generics.Collections" in PASCAL_BUILTIN_UNITS


# =============================================================================
# Regex fallback extraction
# =============================================================================


class TestPascalRegexFallback:
    """Tests PascalMapping.extract_definitions_regex() and extract_imports_regex()."""

    @pytest.fixture
    def mapping(self):
        return PascalMapping()

    def test_extract_definitions_regex_finds_class(self, mapping):
        """extract_definitions_regex detects TMyClass = class."""
        code = "type\n  TMyClass = class(TObject)\n  end;"
        results = mapping.extract_definitions_regex(code)
        names = [r["name"] for r in results]
        assert "TMyClass" in names

    def test_extract_definitions_regex_finds_interface(self, mapping):
        """extract_definitions_regex detects IMyInterface = interface."""
        code = "type\n  IMyInterface = interface\n  end;"
        results = mapping.extract_definitions_regex(code)
        names = [r["name"] for r in results]
        assert "IMyInterface" in names

    def test_extract_definitions_regex_finds_method(self, mapping):
        """extract_definitions_regex detects TMyClass.DoWork method."""
        code = "procedure TMyClass.DoWork;\nbegin end;"
        results = mapping.extract_definitions_regex(code)
        names = [r["name"] for r in results]
        assert "TMyClass.DoWork" in names

    def test_extract_imports_regex_finds_units(self, mapping):
        """extract_imports_regex extracts unit names from a uses clause."""
        code = "uses\n  SysUtils,\n  MyUnit;\n"
        imports = mapping.extract_imports_regex(code)
        assert "SysUtils" in imports
        assert "MyUnit" in imports

    def test_extract_imports_regex_filters_reserved(self, mapping):
        """extract_imports_regex does not include the 'uses' keyword itself."""
        code = "uses SysUtils;\n"
        imports = mapping.extract_imports_regex(code)
        assert "uses" not in imports

    def test_bom_handling(self, mapping):
        """UTF-8 BOM character is stripped before processing uses clause."""
        code = "\ufeffunit Test;\ninterface\nuses UAuth;\nimplementation\nend."
        imports = mapping.extract_imports_regex(code)
        assert "UAuth" in imports


# =============================================================================
# Realistic Delphi fixtures
# =============================================================================


class TestPascalFixtures:
    """Tests with realistic Delphi .pas file fixtures (UAuth.pas, UTypes.pas)."""

    UAUTH_CODE = """\
unit UAuth;
interface
uses
  System.SysUtils,
  System.Classes,
  UTypes;

type
  TAuthService = class(TInterfacedObject, IAuthService)
  private
    FUserName: string;
    FLoggedIn: Boolean;
  public
    constructor Create(const AUserName: string);
    destructor Destroy; override;
    function Login(const APassword: string): Boolean;
    procedure Logout;
    property UserName: string read FUserName;
  end;

implementation

constructor TAuthService.Create(const AUserName: string);
begin
  inherited Create;
  FUserName := AUserName;
  FLoggedIn := False;
end;

destructor TAuthService.Destroy;
begin
  Logout;
  inherited Destroy;
end;

function TAuthService.Login(const APassword: string): Boolean;
begin
  Result := True;
  FLoggedIn := True;
end;

procedure TAuthService.Logout;
begin
  FLoggedIn := False;
end;

end."""

    UTYPES_CODE = """\
unit UTypes;
interface
const
  MAX_RETRIES = 3;
  APP_NAME = 'MyApp';

type
  TOrderStatus = (osNew, osProcessing, osShipped, osDelivered);

  TUserName = string;

  TPoint3D = record
    X, Y, Z: Double;
  end;

  TUtils = class
  public
    class function FormatName(const AFirst, ALast: string): string; static;
  end;

implementation

class function TUtils.FormatName(const AFirst, ALast: string): string;
begin
  Result := AFirst + ' ' + ALast;
end;

end."""

    def test_uauth_imports_extracted(self):
        """UAuth.pas: System.SysUtils, System.Classes, UTypes are extracted."""
        imports = _extract_imports("pascal", self.UAUTH_CODE)
        assert "System.SysUtils" in imports
        assert "System.Classes" in imports
        assert "UTypes" in imports

    def test_uauth_class_extracted(self):
        """UAuth.pas: TAuthService class is detected."""
        syms = _extract_symbols_pascal(self.UAUTH_CODE)
        names = [s["name"] for s in syms]
        assert "TAuthService" in names

    def test_uauth_methods_extracted(self):
        """UAuth.pas: Create, Destroy, Login, Logout methods are all detected."""
        syms = _extract_symbols_pascal(self.UAUTH_CODE)
        names = [s["name"] for s in syms]
        assert "Create" in names
        assert "Destroy" in names
        assert "Login" in names
        assert "Logout" in names

    def test_utypes_constants_extracted(self):
        """UTypes.pas: MAX_RETRIES and APP_NAME are detected as constants."""
        syms = _extract_symbols_pascal(self.UTYPES_CODE)
        names_kinds = {s["name"]: s["kind"] for s in syms}
        assert "MAX_RETRIES" in names_kinds
        assert names_kinds["MAX_RETRIES"] == "constant"
        assert "APP_NAME" in names_kinds
        assert names_kinds["APP_NAME"] == "constant"

    def test_utypes_enum_extracted(self):
        """UTypes.pas: TOrderStatus enum is detected."""
        syms = _extract_symbols_pascal(self.UTYPES_CODE)
        names_kinds = {s["name"]: s["kind"] for s in syms}
        assert "TOrderStatus" in names_kinds
        assert names_kinds["TOrderStatus"] == "enum"

    def test_utypes_record_extracted(self):
        """UTypes.pas: TPoint3D record is detected."""
        syms = _extract_symbols_pascal(self.UTYPES_CODE)
        names = [s["name"] for s in syms]
        assert "TPoint3D" in names

    def test_utypes_type_alias_classification(self):
        """_classify_type_decl correctly classifies various Pascal type declarations."""
        assert _classify_type_decl("TUserName = string") == "type_alias"
        assert _classify_type_decl("TPoint3D = record") == "class"
        assert _classify_type_decl("TOrderStatus = (osNew, osProcessing)") == "enum"
        assert _classify_type_decl("ILogger = interface") == "interface"

    def test_utypes_static_class_method(self):
        """UTypes.pas: TUtils.FormatName static class method is detected."""
        syms = _extract_symbols_pascal(self.UTYPES_CODE)
        names = [s["name"] for s in syms]
        assert "FormatName" in names
