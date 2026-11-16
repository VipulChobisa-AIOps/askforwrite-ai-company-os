"""Authoritative ECDSA NIST P-256 PKI engine for AskforWrite Company OS.

Ported from AFW 2030 Autonomous Trust Engine.
Provides durable asymmetric cryptographic keypair management, safe zero-downtime key
rotation with retired public-key verification, block signing, and verification.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger("afw.company_os.pki")

DEFAULT_KEYS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "keys")
)

_key_lock = threading.RLock()
_node_private_key = None
_node_public_key_pem: str | None = None
_node_key_source: str | None = None
_loaded_env_pem_raw: str | None = None
_loaded_keys_dir: str | None = None
_runtime_retired_public_keys_pem: list[str] = []


def get_keys_dir() -> str:
    return os.environ.get("TRUST_ENGINE_KEYS_DIR", DEFAULT_KEYS_DIR)


def _normalize_pem(raw_pem: str) -> str:
    text = raw_pem.strip()
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    return text.rstrip() + "\n"


def compute_key_id(public_key_pem: str) -> str:
    """Return a deterministic short SHA-256 key identifier for a PEM public key."""
    return hashlib.sha256(public_key_pem.strip().encode("utf-8")).hexdigest()[:16]


def _serialize_public_pem(public_key: ec.EllipticCurvePublicKey) -> str:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def _atomic_write_bytes(path: str, data: bytes, *, mode: int | None = None) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".afw_key_", dir=parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            try:
                os.chmod(tmp_path, mode)
            except OSError:
                pass
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _parse_retired_env_pems() -> list[str]:
    raw = os.environ.get("TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM", "").strip()
    if not raw:
        return []
    parsed: list[str] = []
    if raw.startswith("["):
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str) and item.strip():
                        parsed.append(_normalize_pem(item))
                return parsed
        except Exception:
            pass
    # Fallback: concatenated PEM blocks separated by END PUBLIC KEY marker
    marker = "-----END PUBLIC KEY-----"
    if marker in raw:
        for chunk in raw.split(marker):
            block = chunk.strip()
            if block:
                parsed.append(_normalize_pem(f"{block}\n{marker}"))
        return parsed
    return [_normalize_pem(raw)]


def _retired_keyring_path(keys_dir: str) -> str:
    return os.path.join(keys_dir, "retired_public_keys.json")


def _load_disk_retired_keys(keys_dir: str) -> list[dict[str, str]]:
    path = _retired_keyring_path(keys_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict) and entry.get("public_key_pem")]
    except Exception as exc:
        logger.warning("Failed reading retired keyring '%s': %s", path, exc)
    return []


def _save_disk_retired_keys(keys_dir: str, entries: list[dict[str, str]]) -> None:
    payload = json.dumps(entries, indent=2).encode("utf-8")
    _atomic_write_bytes(_retired_keyring_path(keys_dir), payload, mode=0o644)


def _reset_cached_keys() -> None:
    """Clear in-memory cached signing keys (primarily for deterministic testing)."""
    global _node_private_key, _node_public_key_pem, _node_key_source
    global _loaded_env_pem_raw, _loaded_keys_dir
    with _key_lock:
        _node_private_key = None
        _node_public_key_pem = None
        _node_key_source = None
        _loaded_env_pem_raw = None
        _loaded_keys_dir = None
        _runtime_retired_public_keys_pem.clear()


def init_node_keys(keys_dir: str | None = None) -> tuple[object, str]:
    """Initializes or loads the node's authoritative ECDSA NIST P-256 keypair.

    Precedence:
    1. ``TRUST_ENGINE_PRIVATE_KEY_PEM`` environment secret (stateless multi-worker safe).
    2. Persistent keyring files inside ``keys_dir`` / ``TRUST_ENGINE_KEYS_DIR``.
    3. Atomic first-boot generation on disk (emitting an operational warning in production).
    """
    global _node_private_key, _node_public_key_pem, _node_key_source
    global _loaded_env_pem_raw, _loaded_keys_dir

    with _key_lock:
        env_priv_raw = os.environ.get("TRUST_ENGINE_PRIVATE_KEY_PEM", "").strip()
        if env_priv_raw:
            priv_pem = _normalize_pem(env_priv_raw)
            private_key = serialization.load_pem_private_key(
                priv_pem.encode("utf-8"), password=None
            )
            derived_pub_pem = _serialize_public_pem(private_key.public_key())
            env_pub_raw = os.environ.get("TRUST_ENGINE_PUBLIC_KEY_PEM", "").strip()
            if env_pub_raw and _normalize_pem(env_pub_raw).strip() != derived_pub_pem.strip():
                raise ValueError(
                    "TRUST_ENGINE_PUBLIC_KEY_PEM does not match TRUST_ENGINE_PRIVATE_KEY_PEM."
                )
            _node_private_key = private_key
            _node_public_key_pem = derived_pub_pem
            _node_key_source = "env"
            _loaded_env_pem_raw = env_priv_raw
            _loaded_keys_dir = None
            logger.info(
                "Loaded durable ECDSA NIST P-256 keypair from environment (kid=%s).",
                compute_key_id(derived_pub_pem),
            )
            return _node_private_key, _node_public_key_pem

        target_dir = os.path.abspath(keys_dir or get_keys_dir())
        os.makedirs(target_dir, exist_ok=True)
        try:
            os.chmod(target_dir, 0o700)
        except OSError:
            pass

        private_key_path = os.path.join(target_dir, "node_private_key.pem")
        public_key_path = os.path.join(target_dir, "node_public_key.pem")

        if os.path.exists(private_key_path) and os.path.exists(public_key_path):
            with open(private_key_path, "rb") as f:
                private_key = serialization.load_pem_private_key(f.read(), password=None)
            derived_pub_pem = _serialize_public_pem(private_key.public_key())
            with open(public_key_path, encoding="utf-8") as f:
                disk_pub_pem = _normalize_pem(f.read())
            if disk_pub_pem.strip() != derived_pub_pem.strip():
                logger.warning("Reconciling node_public_key.pem with node_private_key.pem")
                _atomic_write_bytes(public_key_path, derived_pub_pem.encode("utf-8"), mode=0o644)
            _node_private_key = private_key
            _node_public_key_pem = derived_pub_pem
            _node_key_source = "filesystem"
            _loaded_env_pem_raw = None
            _loaded_keys_dir = target_dir
            logger.info(
                "Existing ECDSA NIST P-256 node keypair loaded (kid=%s).",
                compute_key_id(derived_pub_pem),
            )
            return _node_private_key, _node_public_key_pem

        if os.environ.get("APP_ENV", "development").strip().lower() == "production":
            logger.critical(
                "TRUST_ENGINE_PRIVATE_KEY_PEM not set and no keypair found in '%s'; "
                "generating an ECDSA keypair on local filesystem. In ephemeral containers "
                "(e.g., Render without a Persistent Disk), signatures will break across redeploys.",
                target_dir,
            )
        else:
            logger.info("Generating new authoritative ECDSA NIST P-256 node keypair...")

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        private_pem_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = _serialize_public_pem(public_key)

        # Exclusive lockfile avoids two forked workers generating diverging keypairs on first boot.
        lock_path = os.path.join(target_dir, ".node_key_init.lock")
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(lock_fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(lock_fd)
            try:
                if not (os.path.exists(private_key_path) and os.path.exists(public_key_path)):
                    _atomic_write_bytes(private_key_path, private_pem_bytes, mode=0o600)
                    _atomic_write_bytes(public_key_path, public_pem.encode("utf-8"), mode=0o644)
                else:
                    with open(private_key_path, "rb") as f:
                        private_key = serialization.load_pem_private_key(f.read(), password=None)
                    public_pem = _serialize_public_pem(private_key.public_key())
            finally:
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
        except FileExistsError:
            # Another worker holds creation lock; wait briefly or read persisted pair if present.
            if os.path.exists(private_key_path):
                with open(private_key_path, "rb") as f:
                    private_key = serialization.load_pem_private_key(f.read(), password=None)
                public_pem = _serialize_public_pem(private_key.public_key())
            else:
                _atomic_write_bytes(private_key_path, private_pem_bytes, mode=0o600)
                _atomic_write_bytes(public_key_path, public_pem.encode("utf-8"), mode=0o644)

        _node_private_key = private_key
        _node_public_key_pem = public_pem
        _node_key_source = "ephemeral_generated"
        _loaded_env_pem_raw = None
        _loaded_keys_dir = target_dir
        logger.info(
            "Authoritative ECDSA node keypair persisted (kid=%s).",
            compute_key_id(public_pem),
        )
        return _node_private_key, _node_public_key_pem


def ensure_keys_loaded() -> None:
    with _key_lock:
        env_priv_raw = os.environ.get("TRUST_ENGINE_PRIVATE_KEY_PEM", "").strip()
        target_dir = os.path.abspath(get_keys_dir())
        if _node_private_key is None or _node_public_key_pem is None:
            init_node_keys()
            return
        if env_priv_raw and env_priv_raw != _loaded_env_pem_raw:
            init_node_keys()
            return
        if not env_priv_raw and _node_key_source == "env":
            init_node_keys()
            return
        if not env_priv_raw and _loaded_keys_dir and _loaded_keys_dir != target_dir:
            init_node_keys(target_dir)


def get_node_public_key() -> str:
    ensure_keys_loaded()
    assert _node_public_key_pem is not None
    return _node_public_key_pem


def get_trusted_node_public_keys(*, keys_dir: str | None = None) -> list[str]:
    """Return active node public key plus all retired historical node public keys."""
    active = get_node_public_key().strip()
    seen: set[str] = {active}
    ordered: list[str] = [active]

    target_dir = os.path.abspath(keys_dir or get_keys_dir())
    candidates: list[str] = []
    candidates.extend(_parse_retired_env_pems())
    candidates.extend(_runtime_retired_public_keys_pem)
    candidates.extend(entry["public_key_pem"] for entry in _load_disk_retired_keys(target_dir))

    for raw in candidates:
        norm = raw.strip()
        if norm and norm not in seen:
            seen.add(norm)
            ordered.append(norm)
    return ordered


def is_trusted_node_public_key(public_key_pem: str | None, *, keys_dir: str | None = None) -> bool:
    """Return True if public_key_pem matches the active node key or a retired node key."""
    if not public_key_pem or not public_key_pem.strip():
        return False
    candidate = public_key_pem.strip()
    return candidate in get_trusted_node_public_keys(keys_dir=keys_dir)


def get_node_key_status() -> dict[str, Any]:
    """Return non-secret node keypair durability, key ID, and rotation metadata."""
    ensure_keys_loaded()
    assert _node_public_key_pem is not None
    active_kid = compute_key_id(_node_public_key_pem)
    trusted = get_trusted_node_public_keys()
    retired_pems = trusted[1:]
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    source = _node_key_source or "filesystem"
    keys_dir = _loaded_keys_dir or os.path.abspath(get_keys_dir())
    durable = source == "env" or (app_env != "production" and source in ("filesystem", "ephemeral_generated"))
    return {
        "kid": active_kid,
        "source": source,
        "durable": durable,
        "multi_instance_safe": source == "env",
        "keys_dir": None if source == "env" else keys_dir,
        "retired_trusted_keys_count": len(retired_pems),
        "retired_kids": [compute_key_id(p) for p in retired_pems],
    }


def rotate_node_keypair(
    *,
    keys_dir: str | None = None,
    new_private_key_pem: str | None = None,
    persist_to_disk: bool = True,
) -> dict[str, Any]:
    """Safely rotate the active ECDSA NIST P-256 keypair while retaining the previous public key.

    Existing TrustBlocks and P8 marketplace listings signed by the outgoing key continue to
    verify cleanly because the retired public key is archived in both runtime state and
    ``retired_public_keys.json`` (plus exported as JSON for ``TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM``).
    """
    global _node_private_key, _node_public_key_pem, _node_key_source
    global _loaded_env_pem_raw, _loaded_keys_dir

    with _key_lock:
        ensure_keys_loaded()
        assert _node_public_key_pem is not None
        prev_pub_pem = _normalize_pem(_node_public_key_pem)
        prev_kid = compute_key_id(prev_pub_pem)

        if prev_pub_pem.strip() not in {p.strip() for p in _runtime_retired_public_keys_pem}:
            _runtime_retired_public_keys_pem.append(prev_pub_pem)

        target_dir = os.path.abspath(keys_dir or get_keys_dir())
        if persist_to_disk:
            retired_entries = _load_disk_retired_keys(target_dir)
            existing_pems = {e["public_key_pem"].strip() for e in retired_entries}
            if prev_pub_pem.strip() not in existing_pems:
                retired_entries.append(
                    {
                        "kid": prev_kid,
                        "public_key_pem": prev_pub_pem,
                        "retired_at": datetime.now(UTC).isoformat(),
                    }
                )
            _save_disk_retired_keys(target_dir, retired_entries)

        if new_private_key_pem:
            norm_priv = _normalize_pem(new_private_key_pem)
            private_key = serialization.load_pem_private_key(
                norm_priv.encode("utf-8"), password=None
            )
            priv_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        else:
            private_key = ec.generate_private_key(ec.SECP256R1())
            priv_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )

        new_pub_pem = _serialize_public_pem(private_key.public_key())
        new_kid = compute_key_id(new_pub_pem)

        if persist_to_disk:
            private_key_path = os.path.join(target_dir, "node_private_key.pem")
            public_key_path = os.path.join(target_dir, "node_public_key.pem")
            _atomic_write_bytes(private_key_path, priv_bytes, mode=0o600)
            _atomic_write_bytes(public_key_path, new_pub_pem.encode("utf-8"), mode=0o644)
            _loaded_keys_dir = target_dir
            _node_key_source = "filesystem"
        else:
            _node_key_source = "env"

        _node_private_key = private_key
        _node_public_key_pem = new_pub_pem
        _loaded_env_pem_raw = None

        retired_all = get_trusted_node_public_keys(keys_dir=target_dir)[1:]
        logger.info(
            "Rotated ECDSA NIST P-256 keypair: previous_kid=%s new_kid=%s retired_count=%d",
            prev_kid,
            new_kid,
            len(retired_all),
        )
        return {
            "previous_kid": prev_kid,
            "new_kid": new_kid,
            "new_public_key_pem": new_pub_pem,
            "retired_trusted_keys_count": len(retired_all),
            "retired_public_keys_env_json": json.dumps(retired_all),
        }


def sign_block(block_hash: str) -> str:
    """Digitally signs a 64-char block hash using the node's ECDSA NIST P-256 private key.

    Returns a hex-encoded DER signature.
    """
    ensure_keys_loaded()
    assert _node_private_key is not None
    sig_bytes = _node_private_key.sign(
        block_hash.encode("utf-8"), ec.ECDSA(hashes.SHA256())
    )
    return sig_bytes.hex()


def verify_signature(
    public_key_pem: str, block_hash: str, signature_hex: str
) -> bool:
    """Cryptographically verifies an ECDSA DER signature against a block hash and public key PEM."""
    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8")
        )
        sig_bytes = bytes.fromhex(signature_hex)
        public_key.verify(
            sig_bytes, block_hash.encode("utf-8"), ec.ECDSA(hashes.SHA256())
        )
        return True
    except InvalidSignature:
        return False
    except Exception as error:
        logger.warning(f"Signature verification error: {error}")
        return False
