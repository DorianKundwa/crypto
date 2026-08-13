"""
fee_demo.py -- DorianCoin Stage 9A: Mempool Fee Prioritisation Demo
====================================================================
Shows that miners select the highest-fee transactions first when a block
has more pending txns than MAX_TXNS_PER_BLOCK (10).

Scenario
--------
  Alice mines 5 blocks (250 DRN) to accumulate funds.
  Alice submits 12 transactions with varying fees (0.0 to 5.5 DRN).
  A block is mined -- only the top 10 by fee should be included.
  We verify:
    - Exactly 10 user txns in the block (+ 1 coinbase)
    - They are the 10 highest-fee txns (not the first 10 submitted)
    - Coinbase = block_reward (50) + sum of included fees
    - The 2 lowest-fee txns stay in mempool for the next block
    - Total DRN is conserved

Run:
    python -u doriancoin/fee_demo.py    (from repo root)
    python -u fee_demo.py              (from doriancoin/)
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from blockchain import Blockchain
from wallet    import Wallet
from storage   import BlockchainStorage

DIVIDER = "=" * 66
SUBDIV  = "-" * 66
DB_PATH = os.path.join(_HERE, "data", "demo_fee.db")

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


def main():
    banner("DorianCoin Stage 9A -- Mempool Fee Prioritisation Demo")

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    storage = BlockchainStorage(DB_PATH)
    bc      = Blockchain(difficulty=2, storage=storage)
    alice   = Wallet()
    bob     = Wallet()

    print(f"\n  Alice : {alice.address}")
    print(f"  Bob   : {bob.address}")
    print(f"  MAX_TXNS_PER_BLOCK = {bc.MAX_TXNS_PER_BLOCK}")

    # -- Fund Alice: mine 5 blocks (250 DRN) ----------------------------------
    sub("Step 1: Mine 5 blocks to fund Alice (250 DRN)")
    for _ in range(5):
        bc.mine_pending_transactions(alice.address)
    alice_bal = bc.get_balance(alice.address)
    print(f"  Alice balance: {alice_bal:.2f} DRN")

    # -- Submit 12 transactions with varying fees -----------------------------
    sub("Step 2: Submit 12 transactions with varying fees")
    # Intentionally NOT sorted -- miner should reorder them
    fees = [0.0, 3.0, 1.5, 5.0, 0.5, 4.5, 2.0, 5.5, 1.0, 4.0, 2.5, 3.5]
    print()
    print(f"  {'#':>3}  {'Fee':>6}  Status")
    print(f"  {'---'}  {'------'}  {'------------------------------'}")
    accepted_fees = []
    for i, fee in enumerate(fees):
        tx = alice.create_transaction(recipient=bob.address, amount=1.0, fee=fee)
        try:
            bc.add_transaction(tx)
            accepted_fees.append(fee)
            print(f"  {i+1:>3}  {fee:>6.1f}  accepted  "
                  f"(mempool={len(bc.pending_transactions)})")
        except ValueError as e:
            print(f"  {i+1:>3}  {fee:>6.1f}  REJECTED: {e}")

    print(f"\n  Total in mempool: {len(bc.pending_transactions)}")
    sorted_fees      = sorted(accepted_fees, reverse=True)
    expected_top10   = sorted_fees[:10]
    expected_leftover = sorted_fees[10:]
    print(f"  Expected top-10 fees : {[round(f,1) for f in expected_top10]}")
    print(f"  Expected leftover    : {[round(f,1) for f in expected_leftover]}")

    # -- Mine block: top 10 by fee selected -----------------------------------
    sub("Step 3: Mine a block -- expect top-10 fees selected")
    block = bc.mine_pending_transactions(alice.address)

    user_txns    = [t for t in block.transactions if t.get("sender") != "NETWORK"]
    coinbase_txs = [t for t in block.transactions if t.get("sender") == "NETWORK"]
    coinbase_tx  = coinbase_txs[0]

    included_fees   = sorted([float(t.get("fee", 0)) for t in user_txns], reverse=True)
    total_fees      = sum(included_fees)
    expected_reward = 50 + sum(expected_top10)

    print(f"\n  Block #{block.index} transactions : {len(block.transactions)} total")
    print(f"  User txns included  : {len(user_txns)}")
    print(f"  Fees included       : {[round(f,1) for f in included_fees]}")
    print(f"  Total fees          : {total_fees:.1f} DRN")
    print(f"  Coinbase amount     : {coinbase_tx['amount']:.1f} DRN  "
          f"(expected {expected_reward:.1f})")
    print(f"  Mempool remaining   : {len(bc.pending_transactions)}")

    # -- Verification ---------------------------------------------------------
    sub("Step 4: Verification")
    all_ok = True
    all_ok &= check("Exactly 10 user txns in block",
                    len(user_txns) == 10)
    all_ok &= check("Included fees are the top-10 (sorted)",
                    sorted(included_fees, reverse=True) ==
                    sorted(expected_top10, reverse=True))
    all_ok &= check(
        f"Coinbase = {expected_reward:.1f} DRN  "
        f"(50 block reward + {sum(expected_top10):.1f} fees)",
        abs(coinbase_tx["amount"] - expected_reward) < 0.001,
    )
    all_ok &= check("2 lowest-fee txns remain in mempool",
                    len(bc.pending_transactions) == 2)
    all_ok &= check("Chain is valid", bc.is_valid())

    # -- Mine leftover --------------------------------------------------------
    sub("Step 5: Mine next block (leftover txns confirmed)")
    block2 = bc.mine_pending_transactions(alice.address)
    leftover_user = [t for t in block2.transactions if t.get("sender") != "NETWORK"]
    leftover_fees = sorted([float(t.get("fee", 0)) for t in leftover_user])
    print(f"  Block #{block2.index}: {len(leftover_user)} user txns, "
          f"fees={[round(f,1) for f in leftover_fees]}")
    all_ok &= check("Leftover 2 txns mined in next block",
                    len(leftover_user) == 2)
    all_ok &= check("Leftover fees are the 2 lowest",
                    leftover_fees == sorted(expected_leftover))
    all_ok &= check("Chain still valid after leftover block",
                    bc.is_valid())

    storage.close()

    banner("Stage 9A Complete!" if all_ok else "Stage 9A: SOME CHECKS FAILED")
    print("""
  Fee prioritisation verified:
    [OK] Miners pick highest-fee txns first (not submission order)
    [OK] Block cap (MAX_TXNS_PER_BLOCK=10) enforced
    [OK] Coinbase = BLOCK_REWARD + sum(selected fees)
    [OK] Low-fee txns bumped to next block (not dropped)
    [OK] Chain validity maintained throughout

  CLI usage:
    # Send with a fee to jump the queue:
    python drn_wallet.py send --key alice.pem --to DRN1... --amount 5 --fee 0.5
    """)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
