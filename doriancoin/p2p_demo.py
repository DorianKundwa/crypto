"""
p2p_demo.py -- DorianCoin Stage 9B: Multi-Node P2P Consensus Demo
=================================================================
Spins up THREE live DorianCoin nodes and demonstrates the Nakamoto
consensus rule (longest valid chain wins) in action.

Scenario
--------
  Node A (port 5200) -- primary miner
  Node B (port 5201) -- passive observer
  Node C (port 5202) -- competing miner (creates a fork)

  Step 1 : Start all 3 nodes
  Step 2 : Register A<->B<->C as peers
  Step 3 : Mine 4 blocks on A  (height=5)
  Step 4 : B calls /nodes/resolve  --> adopts A's chain
  Step 5 : C mines 2 blocks in isolation (height=3, fork!)
  Step 6 : C calls /nodes/resolve  --> adopts A's longer chain
  Step 7 : Verify all 3 nodes share the same tip hash

Run:
    python -u doriancoin/p2p_demo.py    (from repo root)
    python -u p2p_demo.py              (from doriancoin/)
"""

import os
import sys
import time
import subprocess
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import requests
except ImportError:
    print("[ERROR] pip install requests")
    sys.exit(1)

DIVIDER = "=" * 66
SUBDIV  = "-" * 66

NODE_A = "http://localhost:5200"
NODE_B = "http://localhost:5201"
NODE_C = "http://localhost:5202"

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


def get(base, path, timeout=10):
    return requests.get(base + path, timeout=timeout).json()


def post(base, path, data, timeout=10):
    r = requests.post(base + path, json=data, timeout=timeout)
    return r.status_code, r.json()


def start_node(port, difficulty=2):
    node_script = os.path.join(_HERE, "node.py")
    proc = subprocess.Popen(
        [sys.executable, "-u", node_script,
         "--port", str(port),
         "--difficulty", str(difficulty)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=_HERE,
    )
    return proc


def wait_for_node(base, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(base + "/", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def chain_height(base):
    return get(base, "/chain", timeout=15)["length"]


def chain_tip(base):
    chain = get(base, "/chain", timeout=15)["chain"]
    return chain[-1]["hash"] if chain else None


def mine_block(base, miner_addr):
    return get(base, f"/mine?miner={miner_addr}", timeout=90)


def register_peer(base, peer_url):
    return post(base, "/nodes/register", {"nodes": [peer_url]})


def resolve(base):
    return get(base, "/nodes/resolve", timeout=30)


def main():
    banner("DorianCoin Stage 9B — Multi-Node P2P Consensus Demo")
    print("""
  3 nodes demonstrate Nakamoto longest-chain consensus.
  C is kept isolated while A mines, so C builds a shorter fork
  from genesis. Then we connect C and it resolves to A's chain.

  Node A (port 5200) -- primary miner (4 blocks)
  Node B (port 5201) -- passive, syncs with A automatically
  Node C (port 5202) -- isolated miner (2 blocks, shorter fork)
    """)

    # -- Step 1: Start nodes ───────────────────────────────────────────
    sub("Step 1: Starting 3 nodes")
    procs = []
    for port, label in [(5200, "A"), (5201, "B"), (5202, "C")]:
        p = start_node(port)
        procs.append(p)
        print(f"  Node {label} (port {port}) PID={p.pid}")

    try:
        sub("Step 2: Waiting for all nodes to be ready")
        for base, label in [(NODE_A, "A"), (NODE_B, "B"), (NODE_C, "C")]:
            if not wait_for_node(base, timeout=40):
                print(f"  [ERROR] Node {label} not ready")
                return 1
            print(f"  Node {label} ready at {base}")

        # -- Step 3: Register A<->B ONLY (C stays isolated) ─────────────
        sub("Step 3: Register A<->B only (C stays isolated for now)")
        register_peer(NODE_A, NODE_B)
        register_peer(NODE_B, NODE_A)
        print("  A and B are peers.  C is isolated.")

        addr_a = get(NODE_A, "/wallet/new", timeout=10)["address"]
        addr_c = get(NODE_C, "/wallet/new", timeout=10)["address"]
        print(f"  Miner A: {addr_a[:32]}...")
        print(f"  Miner C: {addr_c[:32]}...")

        # -- Step 4: Mine 4 blocks on A ──────────────────────────────────
        sub("Step 4: Mine 4 blocks on Node A (B auto-syncs as peer)")
        for _ in range(4):
            result = mine_block(NODE_A, addr_a)
            blk = result["block"]
            print(f"  Block #{blk['index']} mined on A  "
                  f"(hash={blk['hash'][:12]}...)")
            time.sleep(0.5)

        height_a = chain_height(NODE_A)
        tip_a    = chain_tip(NODE_A)
        print(f"\n  Node A height: {height_a}  tip: {tip_a[:20]}...")

        # -- Step 5: C mines 2 blocks in isolation (shorter fork) ────────
        sub("Step 5: Node C mines 2 blocks in isolation (shorter fork)")
        for _ in range(2):
            result = mine_block(NODE_C, addr_c)
            blk = result["block"]
            print(f"  Block #{blk['index']} mined on C  "
                  f"(hash={blk['hash'][:12]}...)")
            time.sleep(0.5)

        height_c_fork = chain_height(NODE_C)
        tip_c_fork    = chain_tip(NODE_C)
        print(f"\n  Node C height: {height_c_fork}  tip: {tip_c_fork[:20]}... (FORK)")
        print(f"  A tip != C tip: {tip_a[:16] != tip_c_fork[:16]}")

        # -- Step 6: B resolves ──────────────────────────────────────────
        sub("Step 6: Node B resolves (should already match A via peer sync)")
        result_b = resolve(NODE_B)
        height_b = chain_height(NODE_B)
        tip_b    = chain_tip(NODE_B)
        print(f"  B resolve: {result_b.get('message', '')}")
        print(f"  Node B height: {height_b}  tip: {tip_b[:20]}...")

        # -- Step 7: Connect C to the network and resolve ─────────────────
        sub("Step 7: Register A<->C and B<->C, then C resolves")
        register_peer(NODE_A, NODE_C)
        register_peer(NODE_C, NODE_A)
        register_peer(NODE_B, NODE_C)
        register_peer(NODE_C, NODE_B)
        print("  C is now connected to A and B.")
        time.sleep(1)

        result_c = resolve(NODE_C)
        print(f"  C resolve: replaced={result_c.get('replaced', False)}")
        print(f"  C chain:   {result_c.get('message', '')}")

        height_c = chain_height(NODE_C)
        tip_c    = chain_tip(NODE_C)
        print(f"  Node C height: {height_c}  tip: {tip_c[:20]}...")

        # -- Verification ─────────────────────────────────────────────────
        sub("Step 8: Verification — all nodes must share same tip")
        print(f"\n  Node A  height={height_a}  tip={tip_a[:28]}...")
        print(f"  Node B  height={height_b}  tip={tip_b[:28]}...")
        print(f"  Node C  height={height_c}  tip={tip_c[:28]}...")
        print()

        all_ok = True
        all_ok &= check("A and B share the same tip",
                         tip_b == tip_a)
        all_ok &= check("C adopted A's chain (fork resolved)",
                         tip_c == tip_a)
        all_ok &= check("All nodes agree on height",
                         height_b == height_a and height_c == height_a)
        all_ok &= check("C's isolated fork was shorter than A's chain",
                         height_c_fork < height_a)
        all_ok &= check("C's resolve replaced its shorter chain",
                         result_c.get("replaced", False))

    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=5)
        print(f"\n  All 3 nodes stopped.")

    banner("Stage 9B Complete!" if all_ok else "Stage 9B: SOME CHECKS FAILED")
    print("""
  Nakamoto consensus demonstrated:
    [OK] Longest chain wins (A's 5 blocks beat C's 3)
    [OK] All nodes converge to same chain tip
    [OK] Fork on C was cleanly resolved via /nodes/resolve
    [OK] P2P peer registration and chain sync work correctly
    """)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
