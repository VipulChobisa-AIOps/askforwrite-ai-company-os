"""Authoritative ECDSA NIST P-256 PKI engine for AskforWrite Company OS.

Ported from AFW 2030 Autonomous Trust Engine.
Provides asymmetric cryptographic keypair management, block signing,
and public-key signature verification.
"""

import logging
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger("afw.company_os.pki")

DEFAULT_KEYS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "keys")
)

_node_private_key = None
_node_public_key_pem = None


def get_keys_dir() -> str:
    return os.environ.get("TRUST_ENGINE_KEYS_DIR", DEFAULT_KEYS_DIR)


def init_node_keys(keys_dir: str | None = None) -> tuple[object, str]:
    """Initializes or loads the node's authoritative ECDSA NIST P-256 keypair.

    The private key signs blocks locally. The public key verifies signatures.
    """
    global _node_private_key, _node_public_key_pem

    target_dir = keys_dir or get_keys_dir()
    os.makedirs(target_dir, exist_ok=True)

    private_key_path = os.path.join(target_dir, "node_private_key.pem")
    public_key_path = os.path.join(target_dir, "node_public_key.pem")

    if os.path.exists(private_key_path) and os.path.exists(public_key_path):
        with open(private_key_path, "rb") as f:
            _node_private_key = serialization.load_pem_private_key(
                f.read(), password=None
            )
        with open(public_key_path, "rb") as f:
            _node_public_key_pem = f.read().decode("utf-8")
        logger.info("Existing ECDSA NIST P-256 node keypair loaded.")
        return _node_private_key, _node_public_key_pem

    logger.info("Generating new authoritative ECDSA NIST P-256 node keypair...")
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(private_key_path, "wb") as f:
        f.write(private_pem)

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with open(public_key_path, "wb") as f:
        f.write(public_pem)

    _node_private_key = private_key
    _node_public_key_pem = public_pem.decode("utf-8")
    logger.info("Authoritative ECDSA node keypair generated and persisted.")
    return _node_private_key, _node_public_key_pem


def ensure_keys_loaded():
    global _node_private_key, _node_public_key_pem
    if _node_private_key is None or _node_public_key_pem is None:
        init_node_keys()


def get_node_public_key() -> str:
    ensure_keys_loaded()
    return _node_public_key_pem


def sign_block(block_hash: str) -> str:
    """Digitally signs a 64-char block hash using the node's ECDSA NIST P-256 private key.

    Returns a hex-encoded DER signature.
    """
    ensure_keys_loaded()
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
