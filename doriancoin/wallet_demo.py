"""
wallet_demo.py -- DorianCoin Stage 8: CLI Wallet Demo
======================================================
Launches a background DorianCoin node, then exercises every drn_wallet.py
command against it — no manual curl needed.

What this demo does
-------------------
  1. Start node on port 5100 (difficulty 2, background thread)
  2. Wait for node to be ready
  3. drn_wallet.py new        -- create Alice's wallet
  4. drn_wallet.py address    -- verify the key file
  5. drn_wallet.py info       -- inspect node stats
  6. drn_wallet.py mine       -- mine block 1 (Alice earns 50 DRN)
  7. drn_wallet.py balance    -- Alice's confirmed balance
  8. drn_wallet.py send       -- Alice -> Bob 15 DRN
  9. drn_wallet.py utxo       -- whole network snapshot
 10. drn_wallet.py mine       -- mine block 2 (confirms Alice->Bob)
 11. drn_wallet.py history    -- Alice's full tx history
 12. drn_wallet.py blocks     -- recent 5 blocks
 13. drn_wallet.py balance    -- Bob's balance post-confirmation

Run:
    python -u doriancoin/wallet_demo.py    (from repo root)
    python -u wallet_demo.py              (from doriancoin/)
"""

import os
import sys
import time
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from wallet  import Wallet
import drn_wallet as W   # import the CLI module directly

DIVIDER  = "=" * 66
PORT     = 5100
NODE     = f"http://localhost:{PORT}"
KEYS_DIR = os.path.join(_HERE, "data", "demo_keys")
ALICE_PEM = os.path.join(KEYS_DIR, "alice.pem")
BOB_PEM   = os.path.join(KEYS_DIR, "bob.pem")

# Override the module-level node URL and colour flag
W._NODE  = NODE
W._COLOR = True


def banner(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)
    sys.stdout.flush()


def step(n: int, desc: str) -> None:
    print(f"\n{'─'*66}")
    print(f"  Step {n:02d}: {desc}")
    print(f"{'─'*66}")
    sys.stdout.flush()


def run_cmd(*args) -> int:
    """Run a drn_wallet command using its main() function directly."""
    argv = ["--node", NODE, "--no-color"] + list(str(a) for a in args)
    print(f"\n  $ python drn_wallet.py {' '.join(str(a) for a in args)}")
    print()
    return W.main(argv)


def start_node():
    """Launch node.py in a subprocess on PORT."""
    node_script = os.path.join(_HERE, "node.py")
    proc = subprocess.Popen(
        [sys.executable, "-u", node_script,
         "--port",       str(PORT),
         "--difficulty", "2"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=_HERE,
    )
    return proc


def wait_for_node(timeout: int = 40) -> bool:
    """Poll until / returns 200 or timeout."""
    try:
        import requests
    except ImportError:
        print("  [ERROR] pip install requests  is required for this demo")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{NODE}/", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    banner("DorianCoin Stage 8 — CLI Wallet Demo")
    print("""
  This demo starts a live DorianCoin node then runs every
  drn_wallet.py command against it automatically.
    """)

    os.makedirs(KEYS_DIR, exist_ok=True)
    for f in [ALICE_PEM, BOB_PEM]:
        if os.path.exists(f):
            os.remove(f)

    step(1, f"Starting DorianCoin node on port {PORT}…")
    proc = start_node()
    print(f"  Node PID: {proc.pid}")

    step(2, "Waiting for node to be ready…")
    if not wait_for_node():
        print("  [ERROR] Node did not start in time.")
        proc.terminate()
        sys.exit(1)
    print(f"  Node is ready at {NODE}")

    try:
        step(3, "drn_wallet.py new  — generate Alice's wallet")
        run_cmd("new", "--save", ALICE_PEM)

        step(4, "drn_wallet.py address  — inspect key file")
        run_cmd("address", ALICE_PEM)

        alice = Wallet.load(ALICE_PEM)

        bob = Wallet()
        bob.save(BOB_PEM)
        print(f"\n  Bob's address : {bob.address}")
        print(f"  Bob's key file: {BOB_PEM}")

        step(5, "drn_wallet.py info  — node statistics (before mining)")
        run_cmd("info")

        step(6, "drn_wallet.py mine  — mine block 1 (Alice earns 50 DRN)")
        run_cmd("mine", "--miner", alice.address)

        step(7, "drn_wallet.py balance  — Alice's confirmed balance")
        run_cmd("balance", alice.address)

        step(8, "drn_wallet.py send  — Alice -> Bob 15 DRN")
        run_cmd("send", "--key", ALICE_PEM, "--to", bob.address,
                "--amount", "15", "-y")

        step(9, "drn_wallet.py utxo  — full network balance snapshot")
        run_cmd("utxo")

        step(10, "drn_wallet.py mine  — mine block 2 (confirms Alice->Bob tx)")
        run_cmd("mine", "--miner", alice.address)

        step(11, "drn_wallet.py history  — Alice's transaction history")
        run_cmd("history", alice.address, "--limit", "10")

        step(12, "drn_wallet.py blocks  — recent 5 blocks")
        run_cmd("blocks", "--count", "5")

        step(13, "drn_wallet.py balance  — Bob's balance after confirmation")
        run_cmd("balance", bob.address)

    finally:
        proc.terminate()
        proc.wait(timeout=5)
        print(f"\n  Node (PID {proc.pid}) stopped.")

    banner("Stage 8 Complete!")
    print("""
  Commands demonstrated:
    [OK] new       -- generate + save wallet keypair
    [OK] address   -- inspect and display key file
    [OK] info      -- live node + chain statistics
    [OK] mine      -- trigger Proof-of-Work mining
    [OK] balance   -- confirmed + available balance
    [OK] send      -- sign + broadcast transaction
    [OK] utxo      -- full network balance snapshot
    [OK] history   -- paginated confirmed tx history
    [OK] blocks    -- recent block list

  Usage cheatsheet:
    python doriancoin/drn_wallet.py new --save keys/me.pem
    python doriancoin/drn_wallet.py send --key keys/me.pem --to DRN1... --amount 5
    python doriancoin/drn_wallet.py balance DRN1...
    python doriancoin/drn_wallet.py history DRN1...
    python doriancoin/drn_wallet.py info
    python doriancoin/drn_wallet.py utxo
    """)


if __name__ == "__main__":
    main()
