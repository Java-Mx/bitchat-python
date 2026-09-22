"""
BitChat cryptographic layer — public package API.

Exposes the minimal set of names that higher-level modules (protocol,
application) should import from this package.  Internal module details
(cipher state, HKDF internals) are NOT re-exported here.
"""

from bitchat.crypto.identity import LocalIdentity, calculate_fingerprint
from bitchat.crypto.noise import (
    NoiseRole,
    NoiseSessionState,
    determine_handshake_role,
)
from bitchat.crypto.sessions import NoiseSession

__all__ = [
    "LocalIdentity",
    "NoiseRole",
    "NoiseSession",
    "NoiseSessionState",
    "calculate_fingerprint",
    "determine_handshake_role",
]
