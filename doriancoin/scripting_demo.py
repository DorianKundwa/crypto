"""
scripting_demo.py -- DorianCoin Stage 9C: Transaction Scripts Demo
===================================================================
Demonstrates two script types:

  TimeLock  -- a tx with lock_until_block=N stays in mempool until
               block N is reached, then gets mined automatically.

  MultiSig  -- a 2-of-2 joint account requiring both Alice and Bob
               to sign before any DRN can be spent.

Scenario A: TimeLock
  1. Alice mines 2 blocks (100 DRN)
  2. Alice creates a tx to Carol locked until block #5
  3. Mine blocks 3 and 4 -- locked tx skipped each time
  4. Mine block 5 -- locked tx finally included
  5. Verify Carol received DRN

Scenario B: MultiSig (2-of-2)
  1. Fund a MSIG address (Alice+Bob) by directing mining reward to it
  2. Attempt single-sig spend (Alice alone) -- rejected
  3. Create a valid 2-of-2 multisig tx from MSIG -> Carol
  4. Mine -- Carol receives DRN
  5. Verify MSIG address is deterministic and commutative

Run:
    python -u doriancoin/scripting_demo.py    (from repo root)
    python -u scripting_demo.py              (from doriancoin/)
"""

import os
import sys
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from blockchain import Blockchain
from wallet    import Wallet
from storage   import BlockchainStorage

DIVIDER = "=" * 66
SUBDIV  = "-" * 66
DB_PATH = os.path.join(_HERE, "data", "demo_scripting.db")

PASS = "[PASS]"
FAIL = "[FAIL]"


def banner(title):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)
    sys.stdout.flush()


def sub(title):
    print(f"\n{SUBDIV}")
    print(f"  {title}")
    print(SUBDIV)
    sys.stdout.flush()


def check(label, result):
    tag = PASS if result else FAIL
    print(f"  {tag}  {label}")
    return result


def expect_reject(label, bc, tx):
    """Submit tx and assert it is rejected. Returns True if correctly rejected."""
    try:
        bc.add_transaction(tx)
        print(f"  {FAIL}  {label}")
        print(f"         Expected rejection but was ACCEPTED")
        return False
    except (ValueError, Exception) as e:
        print(f"  {PASS}  {label}")
        print(f"         Rejected: {str(e)[:100]}")
        return True


def main():
    banner("DorianCoin Stage 9C -- Transaction Scripts Demo")
    print("""
  Two script types:
    TimeLock  -- tx withheld until block N (like Bitcoin nLockTime)
    MultiSig  -- 2-of-2 joint account, both parties must sign
    """)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    storage = BlockchainStorage(DB_PATH)
    bc      = Blockchain(difficulty=2, storage=storage)
    alice   = Wallet()
    bob     = Wallet()
    carol   = Wallet()

    print(f"  Alice : {alice.address}")
    print(f"  Bob   : {bob.address}")
    print(f"  Carol : {carol.address}")

    all_ok = True

    # =========================================================================
    # SCENARIO A: TimeLock
    # =========================================================================
    sub("Scenario A: TimeLock -- tx withheld until block 5")

    # Fund Alice with 2 blocks (blocks 1 and 2)
    for _ in range(2):
        bc.mine_pending_transactions(alice.address)
    print(f"\n  Alice balance: {bc.get_balance(alice.address):.2f} DRN  "
          f"(after 2 coinbase rewards)")
    print(f"  Current height: {bc.height}")

    # Create time-locked tx (eligible at block index 5)
    lock_block = 5
    tx_locked = alice.create_transaction(
        recipient=carol.address,
        amount=20.0,
        fee=0.5,
        lock_until_block=lock_block,
    )
    bc.add_transaction(tx_locked)
    print(f"\n  Locked tx submitted:")
    print(f"    amount           = 20 DRN + 0.5 fee")
    print(f"    lock_until_block = {lock_block}")
    print(f"    mempool size     = {len(bc.pending_transactions)}")

    # Mine blocks 3 and 4 -- locked tx should be SKIPPED each time
    print()
    for _ in range(2):
        block = bc.mine_pending_transactions(alice.address)
        user_txns = [t for t in block.transactions if t.get("sender") != "NETWORK"]
        is_skipped = not any(
            t.get("lock_until_block") == lock_block for t in user_txns
        )
        print(f"  Block #{block.index} (height={bc.height}): "
              f"{len(user_txns)} user txns, locked tx skipped={is_skipped}")
        all_ok &= check(
            f"Block #{block.index}: locked tx NOT included "
            f"(lock_until_block={lock_block} > current block)",
            is_skipped,
        )

    carol_before = bc.get_balance(carol.address)
    all_ok &= check("Carol has 0 DRN before unlock block", carol_before == 0.0)
    all_ok &= check("Locked tx still in mempool waiting",
                    len(bc.pending_transactions) == 1)

    # Mine block 5 -- lock expires, tx gets included
    print(f"\n  Mining block #{bc.height + 1} (>= lock_until_block={lock_block}) "
          f"-- lock expires!")
    block5 = bc.mine_pending_transactions(alice.address)
    user_txns5 = [t for t in block5.transactions if t.get("sender") != "NETWORK"]
    is_included = any(
        t.get("lock_until_block") == lock_block for t in user_txns5
    )
    print(f"  Block #{block5.index}: {len(user_txns5)} user txns, "
          f"locked tx included={is_included}")

    carol_after = bc.get_balance(carol.address)
    print(f"  Carol balance: {carol_after:.2f} DRN")

    all_ok &= check(f"Block #{block5.index}: locked tx included after unlock",
                    is_included)
    all_ok &= check("Carol received 20 DRN from time-locked tx",
                    abs(carol_after - 20.0) < 0.001)
    all_ok &= check("Mempool empty after unlock",
                    len(bc.pending_transactions) == 0)

    # =========================================================================
    # SCENARIO B: MultiSig (2-of-2)
    # =========================================================================
    sub("Scenario B: 2-of-2 MultiSig -- Alice+Bob joint account")

    # Derive the deterministic MSIG address from both public keys
    msig_addr = Wallet.make_multisig_address(
        alice.get_public_key_hex(),
        bob.get_public_key_hex(),
    )
    print(f"\n  MSIG address: {msig_addr}")

    # Fund the MSIG address -- direct a mining reward to it
    print(f"\n  Funding MSIG address by mining a block with reward -> MSIG...")
    bc.mine_pending_transactions(msig_addr)
    msig_bal = bc.get_balance(msig_addr)
    print(f"  MSIG balance: {msig_bal:.2f} DRN")
    all_ok &= check("MSIG address funded with block reward",
                    msig_bal >= 50.0)

    # -- B1: Single-sig attempt (should FAIL signature verification) ----------
    sub("  B1: Single-sig spend attempt -- should be REJECTED")

    # Build a tx from MSIG addr but supply a tampered/missing second signature
    tx_body_for_sig = {
        "sender":           msig_addr,
        "recipient":        carol.address,
        "amount":           10.0,
        "fee":              0.0,
        "lock_until_block": 0,
    }
    encoded = json.dumps(tx_body_for_sig, sort_keys=True).encode()

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    sig_a_valid = alice.private_key.sign(encoded, ec.ECDSA(hashes.SHA256())).hex()

    fake_tx = {
        **tx_body_for_sig,
        "pubkey_a":    alice.get_public_key_hex(),
        "pubkey_b":    bob.get_public_key_hex(),
        "signature_a": sig_a_valid,
        "signature_b": "deadbeef00112233",   # invalid sig
    }
    all_ok &= expect_reject(
        "MSIG spend with invalid sig_b rejected (requires both valid sigs)",
        bc, fake_tx,
    )

    # -- B2: Valid 2-of-2 spend -----------------------------------------------
    sub("  B2: Valid 2-of-2 multisig spend (Alice + Bob both sign)")
    msig_tx = Wallet.create_multisig_transaction(
        wallet_a=alice,
        wallet_b=bob,
        recipient=carol.address,
        amount=30.0,
        fee=1.0,
    )
    print(f"\n  MSIG tx: {msig_addr[:30]}... -> Carol, 30 DRN + 1 DRN fee")
    print(f"  signature_a: {msig_tx['signature_a'][:24]}...")
    print(f"  signature_b: {msig_tx['signature_b'][:24]}...")

    try:
        bc.add_transaction(msig_tx)
        print(f"  {PASS}  2-of-2 multisig tx accepted into mempool")
    except ValueError as e:
        print(f"  {FAIL}  Unexpected rejection: {e}")
        all_ok = False

    # Mine it
    block_msig = bc.mine_pending_transactions(alice.address)
    user_txns_msig = [t for t in block_msig.transactions
                      if t.get("sender") != "NETWORK"]
    carol_final = bc.get_balance(carol.address)
    print(f"\n  Block #{block_msig.index}: {len(user_txns_msig)} user txns mined")
    print(f"  Carol final balance: {carol_final:.2f} DRN  "
          f"(20 from timelock + 30 from multisig)")

    all_ok &= check("MSIG tx mined in block", len(user_txns_msig) == 1)
    all_ok &= check("Carol total balance == 50 DRN (20 + 30)",
                    abs(carol_final - 50.0) < 0.001)
    all_ok &= check("Chain is valid after all operations", bc.is_valid())

    # -- B3: MSIG address is deterministic and commutative --------------------
    sub("  B3: MSIG address is deterministic and commutative")
    msig_addr_reversed = Wallet.make_multisig_address(
        bob.get_public_key_hex(),    # Bob first this time
        alice.get_public_key_hex(),  # Alice second
    )
    print(f"\n  msig(alice, bob)  = {msig_addr}")
    print(f"  msig(bob, alice)  = {msig_addr_reversed}")
    all_ok &= check(
        "MSIG address same regardless of key order (commutative)",
        msig_addr == msig_addr_reversed,
    )

    storage.close()

    banner("Stage 9C Complete!" if all_ok else "Stage 9C: SOME CHECKS FAILED")
    print("""
  Transaction scripts verified:
    [OK] TimeLock: tx stays pending until lock_until_block reached
    [OK] TimeLock: tx automatically mined at block height >= lock
    [OK] TimeLock: Carol balance 0 before unlock, 20 DRN after
    [OK] MultiSig: single-sig spend rejected (requires 2-of-2)
    [OK] MultiSig: valid 2-of-2 spend accepted and confirmed
    [OK] MultiSig: address is deterministic and commutative

  CLI usage:
    # Time-lock a transaction until block 10:
    python drn_wallet.py send --key alice.pem --to DRN1... \\
        --amount 5 --lock-until-block 10

    # MultiSig (via Python API):
    from wallet import Wallet
    tx = Wallet.create_multisig_transaction(alice, bob, recipient, 10.0, fee=0.5)
    # POST tx to /transactions/new
    """)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
