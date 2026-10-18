"""Generate local self-custody sovereign Web3 wallet vault for AskforWrite Company OS.

Creates:
1. EVM account (Polygon / Base / Ethereum) via eth-account.
2. Solana account (Ed25519 + Base58) via cryptography + base58.
Saves private keys to git-ignored keys/sovereign_vault.json.
Outputs public receiving addresses.
"""

import json
from pathlib import Path

import base58
from cryptography.hazmat.primitives.asymmetric import ed25519
from eth_account import Account


def generate_sovereign_vault() -> dict[str, str]:
    # 1. Enable unaudited HD wallet features if needed, or create strong random private key
    Account.enable_unaudited_hdwallet_features()
    evm_account = Account.create()
    evm_address = evm_account.address
    evm_private_key = evm_account.key.hex()

    # 2. Generate Solana Ed25519 Keypair
    sol_priv_key = ed25519.Ed25519PrivateKey.generate()
    sol_pub_key = sol_priv_key.public_key()
    sol_pub_bytes = sol_pub_key.public_bytes_raw()
    sol_address = base58.b58encode(sol_pub_bytes).decode("ascii")
    sol_private_bytes = sol_priv_key.private_bytes_raw()
    sol_secret_key = base58.b58encode(sol_private_bytes + sol_pub_bytes).decode("ascii")

    root_dir = Path(__file__).resolve().parent.parent
    vault_dir = root_dir / "keys"
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_file = vault_dir / "sovereign_vault.json"
    wallets_json_file = root_dir / ".sovereign_wallets.json"

    vault_data = {
        "title": "AskforWrite Sovereign Self-Custody Payment Vault",
        "notice": "KEEP THIS FILE PRIVATE. NEVER COMMIT TO GIT. NEVER SHARE PRIVATE KEYS.",
        "created_at": "2026-10-18T23:35:00Z",
        "evm": {
            "networks": ["Polygon (PoS)", "Base L2", "Ethereum Mainnet"],
            "receiving_address": evm_address,
            "private_key": evm_private_key,
        },
        "solana": {
            "networks": ["Solana Mainnet-Beta"],
            "receiving_address": sol_address,
            "private_key_base58": sol_secret_key,
        },
    }

    with open(vault_file, "w", encoding="utf-8") as f:
        json.dump(vault_data, f, indent=2)

    with open(wallets_json_file, "w", encoding="utf-8") as f:
        json.dump(vault_data, f, indent=2)

    print(f"VAULT_SAVED: {vault_file}")
    print(f"WALLETS_SAVED: {wallets_json_file}")
    print(f"EVM_ADDRESS: {evm_address}")
    print(f"SOL_ADDRESS: {sol_address}")

    return {
        "evm_address": evm_address,
        "sol_address": sol_address,
        "vault_path": str(vault_file),
        "wallets_path": str(wallets_json_file),
    }


if __name__ == "__main__":
    generate_sovereign_vault()
