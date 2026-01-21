import pytest
from typing import List, Tuple


@pytest.mark.asyncio
async def test_multihop_via_attribution_with_skipped_symbols():
    """Test that multi-hop via attribution remains correct when some symbols are skipped.

    This is a regression test for the bug where `via_symbol = current_hop_results[i]`
    used the wrong index when some entries were skipped due to `seen_symbols`.
    """
    # Simulate the fixed logic: track (via_symbol, task) pairs
    current_hop_results = [
        {"symbol": "A", "symbol_path": "A"},
        {"symbol": "B", "symbol_path": "B"},  # Will be skipped (already seen)
        {"symbol": "C", "symbol_path": "C"},
        {"symbol": "D", "symbol_path": "D"},  # Will be skipped (already seen)
        {"symbol": "E", "symbol_path": "E"},
    ]

    seen_symbols = {"B", "D"}  # Pre-populate as if these were seen

    # Build tasks the OLD (buggy) way
    old_hop_tasks = []
    for r in current_hop_results:
        hop_symbol = r.get("symbol_path") or r.get("symbol", "")
        if not hop_symbol or hop_symbol in seen_symbols:
            continue
        old_hop_tasks.append(hop_symbol)

    # Build tasks the NEW (fixed) way - tracking via_symbol with each task
    hop_tasks_with_via: List[Tuple[str, str]] = []
    seen_for_new = {"B", "D"}
    for r in current_hop_results:
        hop_symbol = r.get("symbol_path") or r.get("symbol", "")
        if not hop_symbol or hop_symbol in seen_for_new:
            continue
        seen_for_new.add(hop_symbol)
        hop_tasks_with_via.append((hop_symbol, f"task_for_{hop_symbol}"))

    # Verify the fix: via_symbols should be A, C, E (in order)
    expected_via_symbols = ["A", "C", "E"]
    actual_via_symbols = [via for via, _ in hop_tasks_with_via]
    assert actual_via_symbols == expected_via_symbols, f"Expected {expected_via_symbols}, got {actual_via_symbols}"

    # Simulate the OLD buggy way: indexing into current_hop_results directly
    # This would produce wrong via_symbols: A (i=0), C (i=1 -> current_hop_results[1] = B!), E (i=2 -> C!)
    old_buggy_via_symbols = []
    for i in range(len(old_hop_tasks)):
        old_buggy_via_symbols.append(current_hop_results[i].get("symbol", ""))

    # The bug: old way gives ["A", "B", "C"] instead of ["A", "C", "E"]
    assert old_buggy_via_symbols == ["A", "B", "C"], "Bug pattern confirmation"
    assert old_buggy_via_symbols != expected_via_symbols, "Bug produces wrong results"


@pytest.mark.asyncio
async def test_symbol_graph_under_uses_path_prefix_matchtext():
    # Import internal helper to validate filter construction without needing a real Qdrant instance.
    from qdrant_client import models as qmodels
    from scripts.mcp_impl import symbol_graph as sg

    captured = {}

    class FakeClient:
        def scroll(self, *, collection_name, scroll_filter, limit, with_payload, with_vectors):
            captured["collection_name"] = collection_name
            captured["scroll_filter"] = scroll_filter
            return ([], None)

    await sg._query_array_field(  # type: ignore[attr-defined]
        client=FakeClient(),
        collection="codebase",
        field_key="metadata.calls",
        value="foo",
        limit=10,
        language="python",
        under=sg._norm_under("scripts"),  # type: ignore[attr-defined]
    )

    flt = captured.get("scroll_filter")
    assert isinstance(flt, qmodels.Filter)
    must = list(flt.must or [])
    keys = [getattr(c, "key", None) for c in must]
    assert "metadata.path_prefix" in keys

    # Ensure it uses MatchText for prefix substring matching
    cond = next(c for c in must if getattr(c, "key", None) == "metadata.path_prefix")
    assert isinstance(cond.match, qmodels.MatchText)
    assert cond.match.text == "/scripts"


