#!/usr/bin/env python3
"""
Tests for DfmMapping — Delphi VCL/FireMonkey form file mapping (.dfm, .fmx).

Tests cover:
- DfmMapping instantiation and interface compliance
- Tree-sitter queries always return None (no grammar available)
- Component extraction via extract_components()
- Nested component hierarchies
- Event handler extraction
- inherited keyword support
- Realistic main-form DFM fixture with 6 components
"""

import pytest
from typing import List, Dict, Any

from scripts.ingest.language_mappings.dfm import DfmMapping
from scripts.ingest.language_mappings.base import ConceptType


# =============================================================================
# Instantiation
# =============================================================================


class TestDfmMappingInstantiation:
    """DfmMapping instantiates correctly as a BaseMapping subclass."""

    def test_instantiate_without_error(self):
        """DfmMapping instantiates without error."""
        mapping = DfmMapping()
        assert mapping is not None

    def test_has_required_methods(self):
        """DfmMapping implements all required BaseMapping methods."""
        mapping = DfmMapping()
        assert callable(getattr(mapping, "get_query_for_concept"))
        assert callable(getattr(mapping, "extract_name"))
        assert callable(getattr(mapping, "extract_content"))
        assert callable(getattr(mapping, "extract_metadata"))
        assert callable(getattr(mapping, "extract_components"))

    def test_language_name(self):
        """Language name is 'dfm'."""
        mapping = DfmMapping()
        assert mapping.language == "dfm"


# =============================================================================
# Tree-sitter queries (all None — no DFM grammar)
# =============================================================================


class TestDfmQueryAlwaysNone:
    """All concept queries return None for DFM files (no tree-sitter grammar)."""

    @pytest.fixture
    def mapping(self):
        return DfmMapping()

    def test_all_concepts_return_none(self, mapping):
        """Every ConceptType query returns None for DFM."""
        for concept in ConceptType:
            result = mapping.get_query_for_concept(concept)
            assert result is None, f"Expected None for {concept}, got {result!r}"

    def test_definition_query_is_none(self, mapping):
        """DEFINITION query returns None."""
        assert mapping.get_query_for_concept(ConceptType.DEFINITION) is None

    def test_import_query_is_none(self, mapping):
        """IMPORT query returns None."""
        assert mapping.get_query_for_concept(ConceptType.IMPORT) is None

    def test_comment_query_is_none(self, mapping):
        """COMMENT query returns None."""
        assert mapping.get_query_for_concept(ConceptType.COMMENT) is None

    def test_structure_query_is_none(self, mapping):
        """STRUCTURE query returns None."""
        assert mapping.get_query_for_concept(ConceptType.STRUCTURE) is None

    def test_block_query_is_none(self, mapping):
        """BLOCK query returns None."""
        assert mapping.get_query_for_concept(ConceptType.BLOCK) is None


# =============================================================================
# extract_name / extract_content / extract_metadata
# =============================================================================


class TestDfmExtractMethods:
    """DfmMapping extract_ methods work with the captures dict convention."""

    @pytest.fixture
    def mapping(self):
        return DfmMapping()

    def test_extract_name_returns_component_name(self, mapping):
        """extract_name returns the 'name' key from captures."""
        captures = {"name": "Form1", "component_type": "TForm1"}
        result = mapping.extract_name(ConceptType.DEFINITION, captures, b"")
        assert result == "Form1"

    def test_extract_name_fallback_for_missing_key(self, mapping):
        """extract_name returns 'unnamed_component' when 'name' key absent."""
        result = mapping.extract_name(ConceptType.DEFINITION, {}, b"")
        assert result == "unnamed_component"

    def test_extract_content_returns_content(self, mapping):
        """extract_content returns the 'content' key from captures."""
        raw = "object Form1: TForm1\nend"
        captures = {"content": raw}
        result = mapping.extract_content(ConceptType.DEFINITION, captures, b"")
        assert result == raw

    def test_extract_content_empty_for_missing_key(self, mapping):
        """extract_content returns empty string when 'content' key absent."""
        result = mapping.extract_content(ConceptType.DEFINITION, {}, b"")
        assert result == ""

    def test_extract_metadata_has_component_kind(self, mapping):
        """extract_metadata always includes kind='component'."""
        captures = {"component_type": "TForm1", "events": [], "depth": 0}
        meta = mapping.extract_metadata(ConceptType.DEFINITION, captures, b"")
        assert meta["kind"] == "component"

    def test_extract_metadata_includes_component_type(self, mapping):
        """extract_metadata includes the component_type."""
        captures = {"component_type": "TButton", "events": [], "depth": 2}
        meta = mapping.extract_metadata(ConceptType.DEFINITION, captures, b"")
        assert meta["component_type"] == "TButton"

    def test_extract_metadata_includes_depth(self, mapping):
        """extract_metadata includes the nesting depth."""
        captures = {"component_type": "TButton", "events": [], "depth": 3}
        meta = mapping.extract_metadata(ConceptType.DEFINITION, captures, b"")
        assert meta["depth"] == 3

    def test_extract_metadata_includes_events(self, mapping):
        """extract_metadata passes through the events list."""
        events = [{"event": "OnClick", "handler": "BtnClick"}]
        captures = {"component_type": "TButton", "events": events, "depth": 1}
        meta = mapping.extract_metadata(ConceptType.DEFINITION, captures, b"")
        assert meta["events"] == events


# =============================================================================
# Component extraction — DFM fixtures
# =============================================================================


class TestDfmComponentExtraction:
    """Tests DFM component parsing via DfmMapping.extract_components()."""

    SIMPLE_DFM = """\
object Form1: TForm1
  Left = 0
  Top = 0
  Caption = 'Hello'
end"""

    NESTED_DFM = """\
object Form1: TForm1
  object Panel1: TPanel
    object Button1: TButton
      Caption = 'Click'
    end
    object Label1: TLabel
      Caption = 'Label'
    end
  end
end"""

    EVENT_DFM = """\
object Form1: TForm1
  object Button1: TButton
    Caption = 'Click'
    OnClick = Button1Click
    OnDblClick = Button1DblClick
    OnEnter = Button1Enter
  end
end"""

    INHERITED_DFM = """\
inherited frmChild: TfrmChild
  Caption = 'Child Form'
  object ButtonOK: TButton
    OnClick = ButtonOKClick
  end
end"""

    @pytest.fixture
    def mapping(self):
        return DfmMapping()

    def test_simple_component_detected(self, mapping):
        """object Form1: TForm1 → component 'Form1' detected."""
        comps = mapping.extract_components(self.SIMPLE_DFM)
        names = [c["name"] for c in comps]
        assert "Form1" in names

    def test_simple_component_type(self, mapping):
        """object Form1: TForm1 → component_type='TForm1'."""
        comps = mapping.extract_components(self.SIMPLE_DFM)
        form1 = next(c for c in comps if c["name"] == "Form1")
        assert form1["component_type"] == "TForm1"

    def test_simple_component_depth(self, mapping):
        """Root form component has depth=0."""
        comps = mapping.extract_components(self.SIMPLE_DFM)
        form1 = next(c for c in comps if c["name"] == "Form1")
        assert form1["depth"] == 0

    def test_nested_components_detected(self, mapping):
        """Nested components Panel1, Button1, Label1 are all detected."""
        comps = mapping.extract_components(self.NESTED_DFM)
        names = [c["name"] for c in comps]
        assert "Panel1" in names
        assert "Button1" in names
        assert "Label1" in names

    def test_nested_component_depths(self, mapping):
        """Nesting levels are tracked correctly: Panel1=1, Button1=2."""
        comps = mapping.extract_components(self.NESTED_DFM)
        by_name = {c["name"]: c for c in comps}
        assert by_name["Panel1"]["depth"] == 1
        assert by_name["Button1"]["depth"] == 2

    def test_nested_component_parent(self, mapping):
        """Button1's parent is 'Panel1'."""
        comps = mapping.extract_components(self.NESTED_DFM)
        btn = next(c for c in comps if c["name"] == "Button1")
        assert btn["parent"] == "Panel1"

    def test_event_handler_extracted(self, mapping):
        """OnClick = Button1Click is extracted as event reference."""
        comps = mapping.extract_components(self.EVENT_DFM)
        button1 = next(c for c in comps if c["name"] == "Button1")
        event_names = [e["event"] for e in button1["events"]]
        assert "OnClick" in event_names
        handlers = [e["handler"] for e in button1["events"]]
        assert "Button1Click" in handlers

    def test_multiple_event_handlers(self, mapping):
        """Multiple event handlers on one component are all extracted."""
        comps = mapping.extract_components(self.EVENT_DFM)
        button1 = next(c for c in comps if c["name"] == "Button1")
        assert len(button1["events"]) == 3

    def test_inherited_form_detected(self, mapping):
        """'inherited' keyword is parsed like 'object' — component detected."""
        comps = mapping.extract_components(self.INHERITED_DFM)
        names = [c["name"] for c in comps]
        assert "frmChild" in names

    def test_inherited_flag_set(self, mapping):
        """Component created with 'inherited' has inherited=True."""
        comps = mapping.extract_components(self.INHERITED_DFM)
        frmchild = next(c for c in comps if c["name"] == "frmChild")
        assert frmchild["inherited"] is True

    def test_regular_component_not_inherited(self, mapping):
        """Standard 'object' declaration has inherited=False."""
        comps = mapping.extract_components(self.SIMPLE_DFM)
        form1 = next(c for c in comps if c["name"] == "Form1")
        assert form1["inherited"] is False

    def test_component_count_nested(self, mapping):
        """NESTED_DFM produces exactly 4 components."""
        comps = mapping.extract_components(self.NESTED_DFM)
        assert len(comps) == 4


# =============================================================================
# Realistic main-form DFM fixture
# =============================================================================


class TestDfmFixtures:
    """Tests with a realistic main-form DFM fixture."""

    MAIN_FORM_DFM = """\
object frmMain: TfrmMain
  Left = 0
  Top = 0
  Caption = 'Main Application'
  ClientHeight = 600
  ClientWidth = 800
  object pnlTop: TPanel
    Align = alTop
    Height = 50
    object btnLogin: TButton
      Left = 10
      Top = 10
      Caption = 'Login'
      OnClick = btnLoginClick
    end
    object btnLogout: TButton
      Left = 100
      Top = 10
      Caption = 'Logout'
      OnClick = btnLogoutClick
    end
  end
  object pnlMain: TPanel
    Align = alClient
    object grdData: TDBGrid
      Align = alClient
    end
  end
end"""

    @pytest.fixture
    def mapping(self):
        return DfmMapping()

    def test_all_six_components_found(self, mapping):
        """All 6 components (frmMain, pnlTop, btnLogin, btnLogout, pnlMain, grdData) found."""
        comps = mapping.extract_components(self.MAIN_FORM_DFM)
        names = [c["name"] for c in comps]
        assert len(comps) == 6
        assert "frmMain" in names
        assert "pnlTop" in names
        assert "btnLogin" in names
        assert "btnLogout" in names
        assert "pnlMain" in names
        assert "grdData" in names

    def test_event_handlers_found(self, mapping):
        """btnLoginClick and btnLogoutClick event handlers extracted."""
        comps = mapping.extract_components(self.MAIN_FORM_DFM)
        all_handlers = []
        for c in comps:
            all_handlers.extend(e["handler"] for e in c.get("events", []))
        assert "btnLoginClick" in all_handlers
        assert "btnLogoutClick" in all_handlers

    def test_root_component_is_form(self, mapping):
        """The root component is frmMain of type TfrmMain at depth 0."""
        comps = mapping.extract_components(self.MAIN_FORM_DFM)
        root = comps[0]
        assert root["name"] == "frmMain"
        assert root["component_type"] == "TfrmMain"
        assert root["depth"] == 0

    def test_panel_depth_is_one(self, mapping):
        """Top-level panels (pnlTop, pnlMain) are at depth 1."""
        comps = mapping.extract_components(self.MAIN_FORM_DFM)
        by_name = {c["name"]: c for c in comps}
        assert by_name["pnlTop"]["depth"] == 1
        assert by_name["pnlMain"]["depth"] == 1

    def test_buttons_depth_is_two(self, mapping):
        """Buttons inside panels are at depth 2."""
        comps = mapping.extract_components(self.MAIN_FORM_DFM)
        by_name = {c["name"]: c for c in comps}
        assert by_name["btnLogin"]["depth"] == 2
        assert by_name["btnLogout"]["depth"] == 2
