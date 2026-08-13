"""
p2p_demo.py — DorianCoin Stage 3: Two-Node P2P Network Demo
=============================================================
Starts two local DorianCoin nodes as subprocesses, registers them as
peers, mines blocks on node 1, sends a signed transaction, mines again,
then forces node 2 to sync — proving that Nakamoto consensus works.

Run:
    python p2p_demo.py

Requirements:
    Both port 5000 and 5001 must be free.
"""

import subprocess
import sys
import time
import json
import os
import requests
from wallet import Wallet

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NODE1 = "http://localhost:5000"
NODE2 = "http://localhost:5001"

DIVIDER   = "=" * 60
SUBDIV    = "-" * 60
PYTHON    = sys.executable   # use the same Python that launched this script


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def banner(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def sub(title: str) -> None:
    print(f"\n{SUBDIV}")
    print(f"  {title}")
    print(SUBDIV)


def wait_for_node(url: str, label: str, retries: int = 80, delay: float = 0.5) -> bool:
    """Poll a node's / endpoint until it returns HTTP 200 (fully ready).

    The node returns 503 while genesis is still mining, so we specifically
    wait for 200 OK (meaning _node_ready == True inside node.py).
    """
    print(f"  Waiting for {label}  ({url}) ...", end="", flush=True)
    for _ in range(retries):
        try:
            r = requests.get(url + "/", timeout=2)
            if r.status_code == 200:
                print("  ready!")
                return True
            # 503 = still initialising — keep polling silently
        except requests.RequestException:
            pass
        print(".", end="", flush=True)
        time.sleep(delay)
    print("  TIMEOUT!")
    return False


def post(url: str, data: dict) -> dict:
    r = requests.post(url, json=data, timeout=10)
    r.raise_for_status()
    return r.json()


def get(url: str) -> dict:
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def pp(label: str, data: dict) -> None:
    """Pretty-print a labelled response dict (compact)."""
    print(f"\n  [{label}]")
    for k, v in data.items():
        if k == "chain":
            print(f"    chain         : {len(v)} block(s) shown")
        elif k == "block":
            b = v
            print(f"    block.index   : {b['index']}")
            print(f"    block.hash    : {b['hash'][:24]}...")
            print(f"    block.nonce   : {b['nonce']:,}")
            print(f"    block.txns    : {len(b['transactions'])}")
        elif isinstance(v, str) and len(v) > 60:
            print(f"    {k:<16}: {v[:48]}...")
        else:
            print(f"    {k:<16}: {v}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    banner("DorianCoin P2P Network Demo  (Stage 3)")
    print("""
  We will:
    1.  Start Node 1 (port 5000) and Node 2 (port 5001)
    2.  Register them as mutual peers
    3.  Mine 2 blocks on Node 1
    4.  Submit a signed transaction to Node 1
    5.  Mine a 3rd block on Node 1 to confirm the tx
    6.  Verify Node 2 only has the genesis block
    7.  Run /nodes/resolve on Node 2 to sync
    8.  Confirm both nodes share the same chain
    """)

    # ── 1. Launch nodes ───────────────────────────────────────────────
    sub("1. Launching nodes")

    node1_proc = subprocess.Popen(
        [PYTHON, "node.py", "--port", "5000", "--difficulty", "2"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    node2_proc = subprocess.Popen(
        [PYTHON, "node.py", "--port", "5001", "--difficulty", "2"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    try:
        ok1 = wait_for_node(NODE1, "Node 1 :5000")
        ok2 = wait_for_node(NODE2, "Node 2 :5001")
        if not (ok1 and ok2):
            print("\n  ERROR: One or both nodes failed to start. Aborting.")
            return

        # Grab miner addresses from each node
        info1 = get(f"{NODE1}/")
        info2 = get(f"{NODE2}/")
        miner1_addr = info1["miner_address"]
        miner2_addr = info2["miner_address"]

        print(f"\n  Node 1  ID     : {info1['node_id']}")
        print(f"  Node 1  Miner  : {miner1_addr}")
        print(f"  Node 2  ID     : {info2['node_id']}")
        print(f"  Node 2  Miner  : {miner2_addr}")

        # ── 2. Register peers ──────────────────────────────────────────
        sub("2. Registering peers")

        reg1 = post(f"{NODE1}/nodes/register", {"nodes": ["localhost:5001"]})
        print(f"\n  Node 1 registered Node 2  ->  {reg1['message']}")

        reg2 = post(f"{NODE2}/nodes/register", {"nodes": ["localhost:5000"]})
        print(f"  Node 2 registered Node 1  ->  {reg2['message']}")

        # ── 3. Mine block 1 on Node 1 ─────────────────────────────────
        sub("3. Mining block 1 on Node 1")
        print("  (difficulty=3 so this is quick...)")

        mine1 = get(f"{NODE1}/mine")
        pp("Node1 /mine", mine1)

        # ── 4. Create wallets + submit a signed transaction ───────────
        sub("4. Signed transaction  (Alice -> Bob)")

        alice = Wallet()
        bob   = Wallet()
        print(f"\n  Alice : {alice.address}")
        print(f"  Bob   : {bob.address}")

        # Alice needs DRN first — let's use the faucet trick via a
        # NETWORK-sender tx that we insert directly into node 1's pending pool
        # by mining (coinbase pays miner1).  We'll have miner1 send Alice DRN.
        #
        # More realistically: mine again so miner1 has 100 DRN, then transfer.

        sub("4a. Mining block 2 so miner has funds")
        mine2 = get(f"{NODE1}/mine")
        pp("Node1 /mine", mine2)
        miner1_balance = mine2["miner_balance"]
        print(f"\n  Node 1 miner balance: {miner1_balance} DRN")

        # Load the node's own miner wallet to sign the transaction
        miner_pem = os.path.join("data", "miner_5000.pem")
        node1_miner_wallet = Wallet.load(miner_pem)

        print(f"\n  Miner wallet loaded from {miner_pem}")
        assert node1_miner_wallet.address == miner1_addr, \
            "Loaded miner wallet address mismatch!"

        # Sign and submit
        tx = node1_miner_wallet.create_transaction(alice.address, 15)
        print(f"\n  Sending 15 DRN  ->  Alice")
        sub("4b. Submitting signed transaction to Node 1")
        tx_resp = post(f"{NODE1}/transactions/new", tx)
        pp("Node1 /transactions/new", tx_resp)

        # ── 5. Mine block 3 to confirm the tx ─────────────────────────
        sub("5. Mining block 3 on Node 1 (confirms the tx)")
        mine3 = get(f"{NODE1}/mine")
        pp("Node1 /mine", mine3)

        alice_bal = get(f"{NODE1}/balance/{alice.address}")
        print(f"\n  Alice's confirmed balance on Node 1: {alice_bal['balance']} DRN")

        # ── 6. Check Node 2 before sync ────────────────────────────────
        sub("6. Node 2 state BEFORE sync")
        chain2_before = get(f"{NODE2}/chain")
        print(f"\n  Node 2 chain height : {chain2_before['length']}  "
              f"(only genesis — hasn't synced yet)")

        # ── 7. Sync Node 2 via /nodes/resolve ─────────────────────────
        sub("7. Syncing Node 2  (GET /nodes/resolve)")
        resolve2 = get(f"{NODE2}/nodes/resolve")
        pp("Node2 /nodes/resolve", {
            "message":  resolve2["message"],
            "replaced": resolve2["replaced"],
            "height":   resolve2["chain_height"],
        })

        # ── 8. Verify both nodes agree ─────────────────────────────────
        sub("8. Final state comparison")

        chain1_final = get(f"{NODE1}/chain")
        chain2_final = get(f"{NODE2}/chain")

        h1 = chain1_final["length"]
        h2 = chain2_final["length"]

        tip1 = chain1_final["chain"][-1]["hash"]
        tip2 = chain2_final["chain"][-1]["hash"]

        print(f"\n  Node 1  height : {h1}   tip : {tip1[:24]}...")
        print(f"  Node 2  height : {h2}   tip : {tip2[:24]}...")

        if h1 == h2 and tip1 == tip2:
            print("\n  [PASS] Both nodes share the same chain tip! Consensus works.")
        else:
            print("\n  [FAIL] Chains diverged! Something went wrong.")

        # Alice's balance on node 2 (pulled from synced chain)
        alice_bal2 = get(f"{NODE2}/balance/{alice.address}")
        print(f"\n  Alice balance on Node 2 (post-sync): {alice_bal2['balance']} DRN")

        assert alice_bal["balance"] == alice_bal2["balance"], \
            "Balance mismatch between nodes after consensus!"
        print("  [PASS] Balances match across both nodes.")

        # ── Summary ───────────────────────────────────────────────────
        banner("Stage 3 Complete!")
        print("""
  What we built:
    - Flask REST API  (11 endpoints)
    - Two fully independent DorianCoin nodes
    - Signed transactions submitted over HTTP
    - Nakamoto consensus  (longest valid chain wins)
    - Nodes sync automatically after mining

  Next (Stage 4 — Difficulty Retargeting):
    - Adjust difficulty every N blocks
    - Target: 1 block per ~10 seconds
    - Track block timestamps and compute new target

  Curl quick-reference:
    curl http://localhost:5000/
    curl http://localhost:5000/mine
    curl http://localhost:5000/chain
    curl http://localhost:5000/balance/<address>
    curl http://localhost:5001/nodes/resolve
        """)

    finally:
        # ── Clean up node processes ────────────────────────────────────
        print("\n  Shutting down nodes...")
        node1_proc.terminate()
        node2_proc.terminate()
        try:
            node1_proc.wait(timeout=5)
            node2_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            node1_proc.kill()
            node2_proc.kill()
        print("  Nodes stopped.")


if __name__ == "__main__":
    main()
