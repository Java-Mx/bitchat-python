"""Unit tests for LANServer lifecycle, port binding, fallback, and connections."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from bitchat.network.server import DEFAULT_LAN_PORT, LANServer

if TYPE_CHECKING:
    from bitchat.network.connection import LANConnection


@pytest.mark.asyncio
async def test_lan_server_bind_and_connect() -> None:
    """LANServer successfully binds, accepts a connection, and shuts down cleanly."""
    accepted_connections: list[LANConnection] = []

    # Bind to an available ephemeral port
    server = LANServer(
        host="127.0.0.1",
        port=0,
        on_connection_accepted=accepted_connections.append,
    )
    await server.start()

    try:
        assert server.is_listening is True
        assert server.bound_port > 0

        # Connect locally to verify listener accepts incoming TCP streams
        _reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)
        try:
            for _ in range(20):
                if accepted_connections:
                    break
                await asyncio.sleep(0.01)
            assert len(accepted_connections) == 1
            assert accepted_connections[0].is_inbound is True
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await server.stop()

    assert server.is_listening is False
    assert server._server is None


@pytest.mark.asyncio
async def test_lan_server_port_in_use_fallback_to_ephemeral() -> None:
    """When configured port is occupied, LANServer falls back to ephemeral port."""
    # Hold an initial port with a dummy server
    primary_server = await asyncio.start_server(
        lambda r, w: None, host="127.0.0.1", port=0
    )
    occupied_port = primary_server.sockets[0].getsockname()[1]

    lan_server = LANServer(host="127.0.0.1", port=occupied_port)
    try:
        await lan_server.start()
        assert lan_server.is_listening is True
        assert lan_server.bound_port > 0
        assert lan_server.bound_port != occupied_port

        # Verify incoming connection succeeds on the fallback ephemeral port
        _r, writer = await asyncio.open_connection("127.0.0.1", lan_server.bound_port)
        writer.close()
        await writer.wait_closed()
    finally:
        await lan_server.stop()
        primary_server.close()
        await primary_server.wait_closed()


@pytest.mark.asyncio
async def test_lan_server_default_port_constant() -> None:
    """Verify DEFAULT_LAN_PORT is configured to standard BitChat TCP port 41235."""
    assert DEFAULT_LAN_PORT == 41235
    server = LANServer()
    assert server.port == 41235
    assert server.host == "0.0.0.0"


@pytest.mark.asyncio
async def test_lan_server_bind_failure_cleanup_and_reraise() -> None:
    """When both primary port and ephemeral fallback fail, LANServer reraises."""
    lan_server = LANServer(host="127.0.0.1", port=DEFAULT_LAN_PORT)

    err = OSError("System resource exhausted")
    with (
        patch("asyncio.start_server", side_effect=err),
        pytest.raises(OSError, match="System resource exhausted"),
    ):
        await lan_server.start()

    assert lan_server.is_listening is False
    assert lan_server._server is None
    assert lan_server.bound_port == 0


@pytest.mark.asyncio
async def test_lan_server_stop_closes_all_connections() -> None:
    """Stopping LANServer closes all active client connections and server socket."""
    accepted_connections: list[LANConnection] = []
    server = LANServer(
        host="127.0.0.1",
        port=0,
        on_connection_accepted=accepted_connections.append,
    )
    await server.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)
    try:
        for _ in range(20):
            if accepted_connections:
                break
            await asyncio.sleep(0.01)
        assert len(accepted_connections) == 1
        active_conn = accepted_connections[0]

        await server.stop()
        assert server.is_listening is False
        assert not server._connections

        # Client should encounter EOF
        data = await asyncio.wait_for(reader.read(), timeout=1.0)
        assert data == b""
        assert not active_conn.is_connected
    finally:
        writer.close()
        await writer.wait_closed()
