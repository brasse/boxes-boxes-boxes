"""Public identifiers (§6.0)."""

import secrets
import string

ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase
LENGTH = 16


def new_public_id() -> str:
    """
    A base62 identifier of 16 characters.

    `secrets.choice` rather than `random.choice`: these appear in URLs, and the point of
    an external id is that it is unguessable and not enumerable (§7.3).
    """
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
