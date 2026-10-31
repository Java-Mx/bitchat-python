"""Regression tests for MeshRouter rate limiter pruning and memory cleanup."""

from __future__ import annotations

from bitchat.mesh.router import MeshRouter


def test_mesh_router_rate_limiter_pruning() -> None:
    """Validate expired peer entries are pruned from router rate limiter dict."""
    router = MeshRouter(local_peer_id=b"\x00" * 8, rate_limit_per_peer=10)

    now = 500.0
    # Simulate packets from multiple distinct peers
    assert not router.is_rate_limited("peer_1", now=now)
    assert not router.is_rate_limited("peer_2", now=now)
    assert len(router._rate_limiter) == 2

    # Advance time by 2 seconds
    now_later = now + 2.0
    pruned = router.prune_rate_limiter(max_age=1.0, now=now_later)
    assert pruned == 2
    assert len(router._rate_limiter) == 0


def test_mesh_router_rate_limiter_auto_prune_threshold() -> None:
    """Automatic pruning is triggered when rate limiter grows past threshold."""
    router = MeshRouter(local_peer_id=b"\x00" * 8, rate_limit_per_peer=10)

    now = 1000.0
    # Populate with 1005 stale entries
    for i in range(1005):
        router._rate_limiter[f"peer_{i}"] = [now - 5.0]

    assert len(router._rate_limiter) == 1005

    # Calling is_rate_limited for a new peer triggers automatic pruning
    router.is_rate_limited("new_active_peer", now=now)

    # All stale entries should have been pruned, leaving only the new active peer
    assert len(router._rate_limiter) == 1
    assert "new_active_peer" in router._rate_limiter


def test_mesh_router_rate_limit_enforcement_and_reset() -> None:
    """Rate limit enforcement clamps traffic and resets cleanly after window."""
    router = MeshRouter(local_peer_id=b"\x00" * 8, rate_limit_per_peer=3)

    now = 2000.0
    # First 3 packets allowed
    assert not router.is_rate_limited("spammer", now=now)
    assert not router.is_rate_limited("spammer", now=now + 0.1)
    assert not router.is_rate_limited("spammer", now=now + 0.2)

    # 4th packet rate limited
    assert router.is_rate_limited("spammer", now=now + 0.3)

    # Advance time past 1.0s window
    assert not router.is_rate_limited("spammer", now=now + 2.0)
