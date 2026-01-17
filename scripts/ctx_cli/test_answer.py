#!/usr/bin/env python3
"""
Test script for answer command.

Tests the answer command with mock MCP responses to verify:
1. Request formatting
2. Response parsing
3. Error handling
4. Output formatting
"""

import json
import sys
import os
from unittest.mock import Mock, patch

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ctx_cli.commands.answer import (
    answer_command,
    parse_mcp_response,
    format_answer_plain,
    format_citation_plain,
)


def test_parse_mcp_response():
    """Test parsing various MCP response formats."""
    print("Testing MCP response parsing...")

    # Test 1: Standard response with content wrapper
    response1 = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "json": {
                        "answer": "Test answer",
                        "citations": [{"path": "test.py", "start_line": 1, "end_line": 10}]
                    }
                }
            ]
        }
    }
    data1 = parse_mcp_response(response1)
    assert data1 is not None, "Failed to parse standard response"
    assert data1["answer"] == "Test answer", "Answer mismatch"
    assert len(data1["citations"]) == 1, "Citations count mismatch"
    print("  ✓ Standard response parsed correctly")

    # Test 2: Direct result (no content wrapper)
    response2 = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "answer": "Direct answer",
            "citations": []
        }
    }
    data2 = parse_mcp_response(response2)
    assert data2 is not None, "Failed to parse direct response"
    assert data2["answer"] == "Direct answer", "Answer mismatch"
    print("  ✓ Direct response parsed correctly")

    # Test 3: Error response
    response3 = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32600,
            "message": "Bad Request"
        }
    }
    data3 = parse_mcp_response(response3)
    assert data3 is None, "Error response should return None"
    print("  ✓ Error response handled correctly")

    # Test 4: Text content (fallback)
    response4 = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "text": '{"answer": "Text format", "citations": []}'
                }
            ]
        }
    }
    data4 = parse_mcp_response(response4)
    assert data4 is not None, "Failed to parse text content"
    assert data4["answer"] == "Text format", "Answer mismatch"
    print("  ✓ Text content parsed correctly")

    print("All parsing tests passed!\n")


def test_citation_formatting():
    """Test citation formatting."""
    print("Testing citation formatting...")

    citation = {
        "path": "src/main.py",
        "start_line": 10,
        "end_line": 25,
        "score": 0.87
    }

    formatted = format_citation_plain(1, citation)
    assert "src/main.py" in formatted, "Path missing"
    assert "10-25" in formatted, "Line numbers missing"
    assert "0.87" in formatted, "Score missing"
    print("  ✓ Citation formatted correctly")
    print(f"     {formatted}")

    print("All formatting tests passed!\n")


def test_answer_formatting():
    """Test answer formatting."""
    print("Testing answer formatting...")

    answer = "This is a test answer."
    citations = [
        {"path": "test1.py", "start_line": 1, "end_line": 10, "score": 0.9},
        {"path": "test2.py", "start_line": 20, "end_line": 30, "score": 0.8}
    ]
    query = "test query"

    output = format_answer_plain(answer, citations, query)
    assert answer in output, "Answer missing from output"
    assert "test1.py" in output, "First citation missing"
    assert "test2.py" in output, "Second citation missing"
    assert query in output, "Query missing"
    print("  ✓ Answer formatted correctly")

    print("All answer formatting tests passed!\n")


def test_error_handling():
    """Test error handling with mocked requests."""
    print("Testing error handling...")

    # Mock connection error
    with patch('ctx_cli.commands.answer.call_mcp_context_answer') as mock_call:
        mock_call.return_value = {
            "error": {
                "code": -1,
                "message": "Connection failed: Connection refused"
            }
        }

        exit_code = answer_command(
            query="test",
            budget=1000,
            temperature=0.2,
            expand=False,
            json_output=False,
            collection="test"
        )

        assert exit_code == 1, "Should return error code"
        print("  ✓ Connection error handled correctly")

    # Mock timeout error
    with patch('ctx_cli.commands.answer.call_mcp_context_answer') as mock_call:
        mock_call.return_value = {
            "error": {
                "code": -1,
                "message": "Request timed out"
            }
        }

        exit_code = answer_command(
            query="test",
            budget=1000,
            temperature=0.2,
            expand=False,
            json_output=False,
            collection="test"
        )

        assert exit_code == 1, "Should return error code"
        print("  ✓ Timeout error handled correctly")

    print("All error handling tests passed!\n")


def test_json_output():
    """Test JSON output mode."""
    print("Testing JSON output...")

    with patch('ctx_cli.commands.answer.call_mcp_context_answer') as mock_call:
        mock_call.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "answer": "Test answer",
                "citations": [{"path": "test.py", "start_line": 1, "end_line": 10}]
            }
        }

        # Capture stdout
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        exit_code = answer_command(
            query="test",
            budget=1000,
            temperature=0.2,
            expand=False,
            json_output=True,
            collection="test"
        )

        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        assert exit_code == 0, "Should succeed"
        # Verify it's valid JSON
        data = json.loads(output)
        assert data["answer"] == "Test answer", "Answer mismatch in JSON"
        print("  ✓ JSON output works correctly")

    print("All JSON output tests passed!\n")


def run_all_tests():
    """Run all tests."""
    print("="*60)
    print("Running Answer Command Tests")
    print("="*60 + "\n")

    try:
        test_parse_mcp_response()
        test_citation_formatting()
        test_answer_formatting()
        test_error_handling()
        test_json_output()

        print("="*60)
        print("All tests passed!")
        print("="*60)
        return 0

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
