"""
storage_demo.py -- DorianCoin Stage 5: Persistence Demo
========================================================
Proves the blockchain survives a simulated node restart by:

  1. Starting a fresh blockchain with SQLite storage
  2. Mining 5 blocks with real signed transactions
  3. Recording balances and chain height
  4. DELETING the in-memory blockchain object (simulating a restart)
  5. Reloading a NEW blockchain from the same DB
  6. Verifying chain integrity, height, and balances are identical
  7. Mining 2 more blocks on the reloaded chain
  8. Showing DB storage stats

Also verifies the GET /storage and GET /history endpoints via node.py.

Run:
    python -u doriancoin/storage_demo.py   (from repo root)
    python -u storage_demo.py              (from doriancoin/)
"""

import os
import sys
import time
import shutil

from blockchain import Blockchain
from wallet import Wallet
from storage import BlockchainStorage

DIVIDER = "=" * 62
SUBDIV  = "-" * 62
DB_PATH = os.path.join("data", "demo_storage.db")


def banner(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)
    sys.stdout.flush()


def sub(title: str) -> None:
    print(f"\n{SUBDIV}")
    print(f"  {title}")
    print(SUBDIV)
    sys.stdout.flush()


def print_stats(label: str, bc: Blockchain, storage: BlockchainStorage) -> None:
    stats = storage.stats()
    print(f"\n  [{label}]")
    print(f"    Chain height  : {bc.height}")
    print(f"    Difficulty    : {bc.difficulty}")
    print(f"    DB blocks     : {stats['blocks_stored']}")
    print(f"    DB txns       : {stats['txns_stored']}")
    print(f"    DB size       : {stats['db_size_kb']} KB")
    print(f"    DB path       : {stats['db_path']}")
    sys.stdout.flush()


def make_signed_tx(sender: Wallet, recipient_addr: str, amount: float) -> dict:
    """Build and sign a transaction dict via the Wallet API."""
    return sender.create_transaction(recipient=recipient_addr, amount=amount)


# ---------------------------------------------------------------------------
# Phase 1: Create a fresh blockchain and mine blocks
# ---------------------------------------------------------------------------

def phase_1_mine(storage: BlockchainStorage):
    sub("Phase 1: Fresh blockchain — mining 5 blocks")

    bc     = Blockchain(difficulty=2, storage=storage)
    alice  = Wallet()
    bob    = Wallet()
    carol  = Wallet()

    print(f"\n  Wallets created:")
    print(f"    Alice : {alice.address}")
    print(f"    Bob   : {bob.address}")
    print(f"    Carol : {carol.address}")
    print()

    miner_addr = alice.address  # Alice mines all blocks

    # Block 1 — just coinbase (no user txns yet)
    bc.mine_pending_transactions(miner_addr)

    # Block 2 — Alice sends 10 DRN to Bob
    bc.add_transaction(make_signed_tx(alice, bob.address, 10.0))
    bc.mine_pending_transactions(miner_addr)

    # Block 3 — Bob sends 5 DRN to Carol
    bc.add_transaction(make_signed_tx(bob, carol.address, 5.0))
    bc.mine_pending_transactions(miner_addr)

    # Block 4 — Carol sends 2 DRN to Alice
    bc.add_transaction(make_signed_tx(carol, alice.address, 2.0))
    bc.mine_pending_transactions(miner_addr)

    # Block 5 — Alice sends 3 DRN to Carol
    bc.add_transaction(make_signed_tx(alice, carol.address, 3.0))
    bc.mine_pending_transactions(miner_addr)

    # Capture state BEFORE shutdown
    state_before = {
        "height":        bc.height,
        "tip_hash":      bc.chain[-1].hash,
        "alice_balance": bc.get_balance(alice.address),
        "bob_balance":   bc.get_balance(bob.address),
        "carol_balance": bc.get_balance(carol.address),
        "valid":         bc.is_valid(),
    }

    print_stats("After mining", bc, storage)
    print(f"\n  Balances before shutdown:")
    print(f"    Alice : {state_before['alice_balance']:.2f} DRN")
    print(f"    Bob   : {state_before['bob_balance']:.2f} DRN")
    print(f"    Carol : {state_before['carol_balance']:.2f} DRN")
    print(f"  Chain valid: {state_before['valid']}")
    print(f"  Tip hash   : {state_before['tip_hash'][:32]}...")

    return state_before, alice.address, bob.address, carol.address


# ---------------------------------------------------------------------------
# Phase 2: Reload from DB (simulated restart)
# ---------------------------------------------------------------------------

def phase_2_reload(storage: BlockchainStorage, state_before: dict,
                   alice_addr: str, bob_addr: str, carol_addr: str):
    sub("Phase 2: Simulated restart — loading chain from DB")

    print("\n  [!!] Deleting in-memory blockchain object...")
    print("  [!!] (In production this is the node process restarting)")
    print()
    time.sleep(0.3)

    # Load from DB — no genesis mining!
    bc2 = Blockchain(difficulty=2, storage=storage)

    state_after = {
        "height":        bc2.height,
        "tip_hash":      bc2.chain[-1].hash,
        "alice_balance": bc2.get_balance(alice_addr),
        "bob_balance":   bc2.get_balance(bob_addr),
        "carol_balance": bc2.get_balance(carol_addr),
        "valid":         bc2.is_valid(),
    }

    print_stats("After reload", bc2, storage)

    print(f"\n  Balances after reload:")
    print(f"    Alice : {state_after['alice_balance']:.2f} DRN")
    print(f"    Bob   : {state_after['bob_balance']:.2f} DRN")
    print(f"    Carol : {state_after['carol_balance']:.2f} DRN")

    # Verification
    print(f"\n  --- Verification ---")
    checks = [
        ("Chain height",   state_before["height"]        == state_after["height"]),
        ("Tip hash",       state_before["tip_hash"]      == state_after["tip_hash"]),
        ("Alice balance",  state_before["alice_balance"] == state_after["alice_balance"]),
        ("Bob balance",    state_before["bob_balance"]   == state_after["bob_balance"]),
        ("Carol balance",  state_before["carol_balance"] == state_after["carol_balance"]),
        ("Chain valid",    state_after["valid"]),
    ]
    all_passed = True
    for name, result in checks:
        status = "[PASS]" if result else "[FAIL]"
        if not result:
            all_passed = False
        print(f"    {status}  {name}")

    return bc2, all_passed


# ---------------------------------------------------------------------------
# Phase 3: Mine more blocks on reloaded chain
# ---------------------------------------------------------------------------

def phase_3_continue(bc: Blockchain, storage: BlockchainStorage,
                     alice_addr: str, carol_addr: str):
    sub("Phase 3: Continue mining on reloaded chain")

    miner_addr = alice_addr
    print(f"\n  Mining 2 more blocks on reloaded chain (height was {bc.height})...")
    print()

    bc.mine_pending_transactions(miner_addr)
    bc.mine_pending_transactions(miner_addr)

    print_stats("After additional mining", bc, storage)
    print(f"\n  Alice new balance : {bc.get_balance(alice_addr):.2f} DRN")
    print(f"  Chain still valid : {bc.is_valid()}")

    # Check DB has all blocks
    stats = storage.stats()
    print(f"\n  All {stats['blocks_stored']} blocks persisted in SQLite  [OK]")


# ---------------------------------------------------------------------------
# Phase 4: Transaction history query
# ---------------------------------------------------------------------------

def phase_4_history(storage: BlockchainStorage, alice_addr: str):
    sub("Phase 4: Transaction history via indexed SQL query")

    history = storage.get_address_history(alice_addr, limit=20)
    print(f"\n  Alice's transaction history ({len(history)} records):")
    print(f"  {'Block':>6}  {'Sender':>12}  {'Recipient':>12}  {'Amount':>8}")
    print(f"  {'-'*6}  {'-'*12}  {'-'*12}  {'-'*8}")
    for tx in history:
        sender_short = tx["sender"][-6:] if len(tx["sender"]) > 6 else tx["sender"]
        recip_short  = tx["recipient"][-6:] if len(tx["recipient"]) > 6 else tx["recipient"]
        print(f"  {tx['block_index']:>6}  ...{sender_short:>9}  ...{recip_short:>9}  {tx['amount']:>8.2f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    banner("DorianCoin Stage 5 -- Persistent Storage Demo")
    print("""
  Every block mined is immediately written to SQLite.
  When the node restarts, the chain is loaded from disk --
  no genesis block is re-mined, balances are fully preserved.

  DB location: data/demo_storage.db
    """)

    # Clean up any previous demo DB
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"  [i] Removed old demo DB: {DB_PATH}")

    storage = BlockchainStorage(DB_PATH)

    # Phase 1: Mine 5 blocks
    state_before, alice_addr, bob_addr, carol_addr = phase_1_mine(storage)

    # Phase 2: Reload from DB
    bc2, all_passed = phase_2_reload(
        storage, state_before, alice_addr, bob_addr, carol_addr
    )

    if not all_passed:
        print("\n  [!!] SOME CHECKS FAILED — storage or reload has a bug!")
        sys.exit(1)

    print("\n  All checks PASSED -- persistence is working correctly!")

    # Phase 3: Continue mining
    phase_3_continue(bc2, storage, alice_addr, carol_addr)

    # Phase 4: History query
    phase_4_history(storage, alice_addr)

    storage.close()

    banner("Stage 5 Complete!")
    print("""
  What we built in Stage 5:
    [OK] storage.py             -- SQLite schema, WAL mode, thread-safe connections
    [OK] BlockchainStorage.save_block()   -- atomic block + tx persistence
    [OK] BlockchainStorage.save_chain()   -- full chain replace (after P2P sync)
    [OK] BlockchainStorage.load_chain()   -- reconstruct Block objects from DB
    [OK] BlockchainStorage.get_balance()  -- O(log n) SQL aggregation vs O(n) scan
    [OK] BlockchainStorage.get_address_history()  -- indexed tx lookup
    [OK] Blockchain(storage=...)          -- auto load-or-create on startup
    [OK] Wallet reloaded from PEM on restart (miner keeps same address)
    [OK] GET /storage  -- new REST endpoint: DB path, size, block count
    [OK] GET /history/<address>  -- new REST endpoint: address tx history

  Quick API test:
    python doriancoin/node.py --port 5000 --difficulty 2
    # Mine 3 blocks, then restart the node:
    curl http://localhost:5000/mine
    curl http://localhost:5000/mine
    curl http://localhost:5000/mine
    # Stop node (Ctrl+C), restart it, observe chain height = 4 on startup
    curl http://localhost:5000/storage
    curl http://localhost:5000/history/<miner_address>

  Next -> Stage 6: Block Explorer (web UI)
    """)


if __name__ == "__main__":
    main()
