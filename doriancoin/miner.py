"""
miner.py — DorianCoin (DRN) Stage-1 Miner Demo
================================================
Mines three consecutive blocks and prints the miner's running balance.
No real transactions yet — just coinbase (block-reward) payouts.

Run:
    python miner.py
"""

from blockchain import Blockchain

# ─── Config ────────────────────────────────────────────────────────────────
MINER_ADDRESS = "DRN_MINER_001"   # placeholder until wallets are implemented
BLOCKS_TO_MINE = 3
DIFFICULTY = 4                     # leading zeros required in each block hash
# ───────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 60)
    print("  DorianCoin (DRN) — Stage 1 Miner")
    print("=" * 60)
    print()

    blockchain = Blockchain(difficulty=DIFFICULTY)

    # Optionally queue a demo transaction so block 1 carries real data
    blockchain.add_transaction({
        "sender":    "FAUCET",
        "recipient": "DRN_USER_ALICE",
        "amount":    25,
    })

    print(f"Miner address : {MINER_ADDRESS}")
    print(f"Difficulty    : {DIFFICULTY} leading zeros")
    print(f"Block reward  : {Blockchain.BLOCK_REWARD} DRN")
    print()

    for _ in range(BLOCKS_TO_MINE):
        block = blockchain.mine_pending_transactions(MINER_ADDRESS)
        balance = blockchain.get_balance(MINER_ADDRESS)
        print(f"    Miner balance after block {block.index}: {balance} DRN")
        print()

    # ── Chain summary ────────────────────────────────────────────────
    blockchain.print_chain()

    # ── Integrity check ──────────────────────────────────────────────
    valid = blockchain.is_valid()
    print(f"Blockchain valid: {valid}")
    print()

    # ── Tamper demonstration ─────────────────────────────────────────
    print("--- Tampering with block 1 to demonstrate validation ---")
    blockchain.chain[1].transactions[0]["amount"] = 999_999
    print(f"Blockchain valid after tamper: {blockchain.is_valid()}")


if __name__ == "__main__":
    main()
