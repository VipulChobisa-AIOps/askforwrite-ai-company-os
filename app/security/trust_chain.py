"""Cryptographic SHA-256 Merkle Ledger and Trust Chain.

Ported from AFW 2030 Autonomous Trust Engine for AskforWrite AI Company OS.
Provides tamper-evident block sealing, SHA-256 hash chaining,
and ECDSA NIST P-256 digital signature verification for completed TaskRecords.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import TrustBlock
from app.security.ecdsa_pki import get_node_public_key, sign_block, verify_signature

logger = logging.getLogger("afw.company_os.trust_chain")

GENESIS_PREV_HASH = "0" * 64
GENESIS_TIMESTAMP_STR = "2026-01-01T00:00:00+00:00"


def compute_payload_hash(payload: dict) -> str:
    """Computes deterministic SHA-256 hash of a JSON payload dictionary.

    Keys are strictly sorted with no redundant whitespace.
    """
    canonical_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_block_hash(
    index: int, timestamp_str: str, prev_hash: str, payload_hash: str
) -> str:
    """Computes deterministic SHA-256 hash of a block header.

    Format: index:timestamp_str:prev_hash:payload_hash
    """
    header = f"{index}:{timestamp_str}:{prev_hash}:{payload_hash}"
    return hashlib.sha256(header.encode("utf-8")).hexdigest()


def format_block_timestamp(dt: datetime | None) -> str:
    """Standardizes datetime string formatting for hashing.

    Ensures UTC timezone is always explicitly normalized with +00:00.
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def ensure_genesis_block(db: Session) -> TrustBlock:
    """Guarantees Block 0 (Genesis Block) exists in the database."""
    genesis = db.query(TrustBlock).filter(TrustBlock.index == 0).first()
    if genesis:
        return genesis

    logger.info("Initializing Trust Chain Genesis Block (Block #0)...")
    genesis_payload = {
        "title": "AskforWrite AI Company OS Trust Ledger Genesis",
        "protocol": "AFW-COMPANY-OS-TRUST-CHAIN-V2",
        "standard": "SHA-256 Merkle Hash-Chaining with ECDSA NIST P-256 Signatures",
        "authority": "Vipul Chobisa (Owner)",
        "created_at": GENESIS_TIMESTAMP_STR,
    }
    payload_hash = compute_payload_hash(genesis_payload)
    block_hash = compute_block_hash(
        0, GENESIS_TIMESTAMP_STR, GENESIS_PREV_HASH, payload_hash
    )
    signature = sign_block(block_hash)
    public_key = get_node_public_key()

    genesis_dt = datetime.fromisoformat(GENESIS_TIMESTAMP_STR)
    genesis_block = TrustBlock(
        index=0,
        timestamp=genesis_dt,
        task_id=None,
        capability_name="genesis",
        action="genesis_sealing",
        payload_data=genesis_payload,
        payload_hash=payload_hash,
        prev_hash=GENESIS_PREV_HASH,
        block_hash=block_hash,
        signature=signature,
        public_key=public_key,
        sealed_by="AFW-COMPANY-OS-GENESIS",
    )

    db.add(genesis_block)
    db.commit()
    db.refresh(genesis_block)
    logger.info(
        f"Genesis Block sealed: index=0 hash={block_hash[:16]}...{block_hash[-8:]}"
    )
    return genesis_block


def seal_task_to_block(
    db: Session,
    task_id: str,
    capability_name: str,
    action: str,
    payload: dict,
    sealed_by: str = "AFW-TRUST-ENGINE",
    commit: bool = True,
) -> TrustBlock:
    """Cryptographically seals a completed TaskRecord or workflow action

    into an immutable TrustBlock appended to the local SHA-256 hash-chain.
    """
    ensure_genesis_block(db)
    task_id = str(task_id)[:36]

    tip = db.query(TrustBlock).order_by(TrustBlock.index.desc()).first()
    new_index = tip.index + 1
    prev_hash = tip.block_hash

    now_dt = datetime.now(UTC)
    timestamp_str = format_block_timestamp(now_dt)

    block_payload = {
        "task_id": task_id,
        "capability": capability_name,
        "action": action,
        "data": payload,
        "timestamp": timestamp_str,
    }

    payload_hash = compute_payload_hash(block_payload)
    block_hash = compute_block_hash(
        new_index, timestamp_str, prev_hash, payload_hash
    )
    signature = sign_block(block_hash)
    public_key = get_node_public_key()

    block = TrustBlock(
        index=new_index,
        timestamp=now_dt,
        task_id=task_id,
        capability_name=capability_name,
        action=action,
        payload_data=block_payload,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        block_hash=block_hash,
        signature=signature,
        public_key=public_key,
        sealed_by=sealed_by,
    )

    db.add(block)
    if commit:
        db.commit()
        db.refresh(block)
    else:
        db.flush()
    logger.info(
        f"Sealed Block #{new_index} for Task [{task_id}] with hash: {block_hash[:16]}..."
    )
    return block


def verify_chain_integrity(db: Session) -> dict[str, Any]:
    """Scans and cryptographically verifies the entire Trust Chain from Block 0 to Tip.

    Validates:
      1. Genesis Block integrity.
      2. Consecutive index monotonicity.
      3. Exact prev_hash linkage (SHA-256 Merkle chain).
      4. Exact payload_hash recalculation.
      5. Exact block_hash recalculation.
      6. Asymmetric ECDSA NIST P-256 signature validity.
    """
    ensure_genesis_block(db)
    blocks = db.query(TrustBlock).order_by(TrustBlock.index.asc()).all()

    errors = []
    total = len(blocks)
    prev_block = None

    for b in blocks:
        # 1. Verify index sequence
        if prev_block is None and b.index != 0:
            errors.append(f"Block #{b.index}: Genesis block must have index 0")
        elif prev_block is not None and b.index != prev_block.index + 1:
            errors.append(
                f"Block #{b.index}: Non-consecutive index after #{prev_block.index}"
            )

        # 2. Verify prev_hash
        if prev_block is None:
            if b.prev_hash != GENESIS_PREV_HASH:
                errors.append(
                    f"Block #0: Genesis prev_hash mismatch: expected {GENESIS_PREV_HASH}, got {b.prev_hash}"
                )
        else:
            if b.prev_hash != prev_block.block_hash:
                errors.append(
                    f"Block #{b.index}: Linkage broken: expected prev_hash {prev_block.block_hash}, got {b.prev_hash}"
                )

        # 3. Verify payload hash
        expected_payload_hash = compute_payload_hash(b.payload_data)
        if b.payload_hash != expected_payload_hash:
            errors.append(
                f"Block #{b.index}: Payload hash mismatch: expected {expected_payload_hash}, got {b.payload_hash}"
            )

        # 4. Verify block hash
        ts_str = format_block_timestamp(b.timestamp)
        expected_block_hash = compute_block_hash(
            b.index, ts_str, b.prev_hash, b.payload_hash
        )
        if b.block_hash != expected_block_hash:
            errors.append(
                f"Block #{b.index}: Block hash mismatch: expected {expected_block_hash}, got {b.block_hash}"
            )

        # 5. Verify ECDSA signature
        sig_valid = verify_signature(b.public_key, b.block_hash, b.signature)
        if not sig_valid:
            errors.append(f"Block #{b.index}: ECDSA digital signature INVALID")

        prev_block = b

    return {
        "chain_valid": len(errors) == 0,
        "total_blocks": total,
        "genesis_hash": blocks[0].block_hash if blocks else None,
        "tip_index": blocks[-1].index if blocks else None,
        "tip_hash": blocks[-1].block_hash if blocks else None,
        "errors": errors,
    }


# Backward-compatible alias
verify_chain = verify_chain_integrity

