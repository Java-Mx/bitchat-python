"""GATT discovery and validation for BitChat services and characteristics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bitchat.exceptions import BLEGATTError
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)

if TYPE_CHECKING:
    from bleak.backends.characteristic import BleakGATTCharacteristic

logger = logging.getLogger(__name__)


class GATTManager:
    """Discovers and validates BitChat GATT service and characteristic layout."""

    def __init__(
        self,
        service_uuid: str = BITCHAT_SERVICE_UUID,
        characteristic_uuid: str = BITCHAT_CHARACTERISTIC_UUID,
    ) -> None:
        self.service_uuid = service_uuid.lower()
        self.characteristic_uuid = characteristic_uuid.lower()

    async def discover(self, client: Any) -> Any:
        """Discover and validate the BitChat service and characteristic."""
        if not getattr(client, "is_connected", False):
            raise BLEGATTError(
                f"Cannot discover GATT on disconnected client {client.address}"
            )

        try:
            services = getattr(client, "services", None)
            if not services and hasattr(client, "get_services"):
                services = await client.get_services()
        except Exception as e:
            raise BLEGATTError(
                f"Failed to retrieve GATT services from {client.address}: {e}"
            ) from e

        if services is None:
            raise BLEGATTError(
                f"No GATT services discovered on client {client.address}"
            )

        # 1. Locate BitChat Service
        service_found = False
        target_char: BleakGATTCharacteristic | None = None

        for service in services:
            if str(service.uuid).lower() == self.service_uuid:
                service_found = True
                for char in service.characteristics:
                    if str(char.uuid).lower() == self.characteristic_uuid:
                        target_char = char
                        break
                break

        # Fallback: search all characteristics if service nesting is flattened
        if target_char is None and services:
            for service in services:
                for char in service.characteristics:
                    if str(char.uuid).lower() == self.characteristic_uuid:
                        target_char = char
                        service_found = True
                        break
                if target_char is not None:
                    break

        if not service_found:
            raise BLEGATTError(
                f"BitChat service {self.service_uuid} not found on {client.address}"
            )

        if target_char is None:
            raise BLEGATTError(
                f"BitChat characteristic {self.characteristic_uuid} not found "
                f"on {client.address}"
            )

        # 2. Validate Characteristic Properties
        props = [p.lower() for p in (target_char.properties or [])]
        can_write = any(
            p in props
            for p in ("write-without-response", "write", "write without response")
        )
        can_notify = any(p in props for p in ("notify", "indicate"))

        if not can_write:
            logger.warning(
                "Characteristic %s does not report write properties (found: %s)",
                target_char.uuid,
                props,
            )
        if not can_notify:
            logger.warning(
                "Characteristic %s does not report notify properties (found: %s)",
                target_char.uuid,
                props,
            )

        logger.debug(
            "Resolved BitChat GATT characteristic %s on %s (properties=%s)",
            target_char.uuid,
            client.address,
            props,
        )
        return target_char
