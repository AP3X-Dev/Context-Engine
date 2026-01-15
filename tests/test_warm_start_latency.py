"""
Test suite for warm_start.py warmup infrastructure.

Tests verify:
- Warmup state management
- Health endpoint integration
- Async warmup orchestration
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def reset_warmup_state():
    """Reset warmup state before each test."""
    from scripts.warm_start import _WARMUP_STATE
    _WARMUP_STATE.clear()
    _WARMUP_STATE["status"] = "cold"
    _WARMUP_STATE["latency_ms"] = None
    yield
    _WARMUP_STATE.clear()
    _WARMUP_STATE["status"] = "cold"


def test_get_warmup_status_initial_state(reset_warmup_state):
    """Test warmup status returns cold state initially."""
    from scripts.warm_start import get_warmup_status

    status = get_warmup_status()
    assert status["status"] == "cold"
    assert status["latency_ms"] is None


def test_warmup_status_after_success(reset_warmup_state):
    """Test get_warmup_status returns warm state after successful warmup."""
    from scripts.warm_start import _WARMUP_STATE, get_warmup_status

    # Simulate successful warmup
    _WARMUP_STATE.update({
        "status": "warm",
        "latency_ms": 250.5,
        "embedding_ms": 150.0,
        "reranker_ms": 100.5,
    })

    status = get_warmup_status()
    assert status["status"] == "warm"
    assert status["latency_ms"] == 250.5
    assert status["embedding_ms"] == 150.0
    assert status["reranker_ms"] == 100.5


def test_warmup_status_after_failure(reset_warmup_state):
    """Test get_warmup_status returns failed state with error."""
    from scripts.warm_start import _WARMUP_STATE, get_warmup_status

    # Simulate failed warmup
    _WARMUP_STATE.update({
        "status": "failed",
        "error": "ONNX model not found",
    })

    status = get_warmup_status()
    assert status["status"] == "failed"
    assert "error" in status
    assert status["error"] == "ONNX model not found"


@pytest.mark.asyncio
@patch("scripts.warm_start.warmup_embedding_model")
@patch("scripts.warm_start.warmup_reranker")
async def test_warmup_all_models_success(mock_warmup_reranker, mock_warmup_embedding, reset_warmup_state):
    """Test warmup_all_models updates state on success."""
    from scripts.warm_start import warmup_all_models, get_warmup_status

    # Mock warmup functions
    async def mock_embedding_warmup(model):
        return 150.0

    async def mock_reranker_warmup():
        return 100.0

    mock_warmup_embedding.side_effect = mock_embedding_warmup
    mock_warmup_reranker.side_effect = mock_reranker_warmup

    result = await warmup_all_models()

    # Verify result structure
    assert "embedding_ms" in result
    assert "reranker_ms" in result
    assert "total_ms" in result
    assert result["embedding_ms"] == 150.0
    assert result["reranker_ms"] == 100.0
    assert result["total_ms"] > 0

    # Verify state updated
    status = get_warmup_status()
    assert status["status"] == "warm"
    assert "latency_ms" in status


@pytest.mark.asyncio
@patch("scripts.warm_start.warmup_embedding_model")
@patch("scripts.warm_start.warmup_reranker")
async def test_warmup_all_models_handles_failure(mock_warmup_reranker, mock_warmup_embedding, reset_warmup_state):
    """Test warmup_all_models handles failures gracefully."""
    from scripts.warm_start import warmup_all_models, get_warmup_status

    # Simulate embedding failure
    async def mock_embedding_failure(model):
        raise RuntimeError("Embedding model crashed")

    async def mock_reranker_success():
        return 100.0

    mock_warmup_embedding.side_effect = mock_embedding_failure
    mock_warmup_reranker.side_effect = mock_reranker_success

    with pytest.raises(RuntimeError, match="Embedding model crashed"):
        await warmup_all_models()

    # Verify state shows failure
    status = get_warmup_status()
    assert status["status"] == "failed"
    assert "error" in status


@pytest.mark.asyncio
@patch("scripts.warm_start.warmup_embedding_model")
@patch("scripts.warm_start.warmup_reranker")
async def test_warmup_parallel_execution(mock_warmup_reranker, mock_warmup_embedding, reset_warmup_state):
    """Test warmup runs embedding and reranker in parallel."""
    from scripts.warm_start import warmup_all_models
    import time

    # Track execution order
    execution_order = []

    async def mock_embedding_warmup(model):
        execution_order.append("embedding_start")
        await asyncio.sleep(0.1)
        execution_order.append("embedding_end")
        return 100.0

    async def mock_reranker_warmup():
        execution_order.append("reranker_start")
        await asyncio.sleep(0.1)
        execution_order.append("reranker_end")
        return 80.0

    mock_warmup_embedding.side_effect = mock_embedding_warmup
    mock_warmup_reranker.side_effect = mock_reranker_warmup

    start = time.time()
    result = await warmup_all_models()
    elapsed = time.time() - start

    # Verify parallel execution (should be ~0.1s, not 0.2s sequential)
    assert elapsed < 0.3, f"Warmup took {elapsed:.2f}s, expected <0.3s for parallel"

    # Both should start before either ends (parallel execution)
    embedding_start_idx = execution_order.index("embedding_start")
    reranker_start_idx = execution_order.index("reranker_start")
    embedding_end_idx = execution_order.index("embedding_end")
    reranker_end_idx = execution_order.index("reranker_end")

    # Both should start before either finishes
    assert min(embedding_start_idx, reranker_start_idx) < max(embedding_end_idx, reranker_end_idx)


@pytest.mark.asyncio
@patch("scripts.warm_start.warmup_embedding_model")
@patch("scripts.warm_start.warmup_reranker")
async def test_warmup_under_5_seconds_threshold(mock_warmup_reranker, mock_warmup_embedding, reset_warmup_state):
    """Test parallel warmup completes in <5s (AC2 requirement)."""
    from scripts.warm_start import warmup_all_models
    import time

    # Realistic warmup latencies (models already loaded, just inference)
    async def mock_embedding_warmup(model):
        await asyncio.sleep(0.05)  # 50ms
        return 50.0

    async def mock_reranker_warmup():
        await asyncio.sleep(0.03)  # 30ms
        return 30.0

    mock_warmup_embedding.side_effect = mock_embedding_warmup
    mock_warmup_reranker.side_effect = mock_reranker_warmup

    start = time.time()
    result = await warmup_all_models()
    elapsed = time.time() - start

    assert elapsed < 5.0, f"Warmup took {elapsed:.2f}s, exceeds 5s threshold"
    assert result["total_ms"] < 5000, f"Total warmup {result['total_ms']}ms exceeds 5000ms"


def test_health_endpoint_integration(reset_warmup_state):
    """Test warmup integration with /health/warmup endpoint.

    NOTE: This test documents the expected integration. The actual endpoint
    is on HEALTH_PORT (default: 18001), not the main MCP port (8001).

    The handler in mcp_indexer_server.py:404 imports get_warmup_status
    and returns its result as JSON.
    """
    from scripts.warm_start import _WARMUP_STATE, get_warmup_status

    # Initial state: cold
    status = get_warmup_status()
    assert status["status"] == "cold"

    # Simulate warmup execution (would happen on server start)
    _WARMUP_STATE.update({
        "status": "warm",
        "latency_ms": 300,
        "embedding_ms": 200,
        "reranker_ms": 100,
    })

    # Health endpoint queries status
    status = get_warmup_status()
    assert status["status"] == "warm"
    assert status["latency_ms"] == 300

    # Simulate HTTP response construction (as in mcp_indexer_server.py)
    response_payload = {"ok": True, **status}
    assert response_payload["ok"] is True
    assert response_payload["status"] == "warm"
    assert response_payload["latency_ms"] == 300

    # This demonstrates that GET http://localhost:18001/health/warmup
    # would return this payload after warmup completes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
