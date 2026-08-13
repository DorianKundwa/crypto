#!/usr/bin/env python
"""
drn_wallet.py -- DorianCoin (DRN) CLI Wallet Tool  (Stage 8)
=============================================================
A full command-line wallet for DorianCoin.  Generates keys, checks
balances, sends signed transactions, and inspects the live chain --
all without touching a browser.

Usage
-----
    python drn_wallet.py <command> [options]

Commands
--------
    new       Generate a new wallet and save the private key
    address   Show the address stored in a key file
    balance   Query confirmed and available balance for an address
    send      Sign and broadcast a transaction to a node
    history   Show transaction history for an address
    utxo      Show all confirmed balances on the network
    info      Display live node and chain statistics
    blocks    List recent blocks from the chain
    mine      Trigger Proof-of-Work mining on the node

Global Options
--------------
    --node   Node base URL  (default: http://localhost:5000)
    --no-color   Disable ANSI color output

Examples
--------
    python drn_wallet.py new --save keys/alice.pem
    python drn_wallet.py balance DRN1Alice...
    python drn_wallet.py send --key keys/alice.pem --to DRN1Bob... --amount 10
    python drn_wallet.py history DRN1Alice... --limit 20
    python drn_wallet.py utxo
    python drn_wallet.py info
    python drn_wallet.py blocks --count 5
    python drn_wallet.py mine
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# ── resolve doriancoin/ imports regardless of cwd ─────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from wallet import Wallet
except ImportError as e:
    print(f"[ERROR] Cannot import wallet.py: {e}")
    print("  Run from repo root:  python doriancoin/drn_wallet.py ...")
    sys.exit(1)

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ─── ANSI colour helpers ───────────────────────────────────────────────────
_COLOR = True   # overridden by --no-color

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text

def cyan(t):    return _c("96", str(t))
def green(t):   return _c("92", str(t))
def yellow(t):  return _c("93", str(t))
def red(t):     return _c("91", str(t))
def dim(t):     return _c("2",  str(t))
def bold(t):    return _c("1",  str(t))
def purple(t):  return _c("95", str(t))

# ─── Output helpers ────────────────────────────────────────────────────────
W = 64   # box width

def header(title: str) -> None:
    bar = "─" * (W - 2)
    print(f"\n┌{bar}┐")
    pad = " " * ((W - 2 - len(title)) // 2)
    print(f"│{pad}{bold(title)}{pad}│")
    print(f"└{bar}┘")

def section(title: str) -> None:
    print(f"\n  {cyan('▸')} {bold(title)}")
    print(f"  {'─' * (W - 4)}")

def kv(key: str, value, width: int = 14) -> None:
    print(f"  {dim(key.ljust(width))} {value}")

def ok(msg: str) -> None:
    print(f"  {green('✓')} {msg}")

def err(msg: str) -> None:
    print(f"  {red('✗')} {msg}", file=sys.stderr)

def warn(msg: str) -> None:
    print(f"  {yellow('!')} {msg}")

def blank() -> None:
    print()

def table(headers: list[str], rows: list[list], widths: list[int]) -> None:
    """Print an aligned table."""
    blank()
    # header row
    hdr = "  "
    for h, w in zip(headers, widths):
        hdr += dim(h.ljust(w)) + "  "
    print(hdr)
    # separator
    print("  " + "  ".join(dim("─" * w) for w in widths))
    # rows
    for row in rows:
        line = "  "
        for cell, w in zip(row, widths):
            raw   = str(cell)
            # strip ANSI for width calculation
            plain = raw
            for code in ["\033[96m", "\033[92m", "\033[91m", "\033[93m",
                         "\033[95m", "\033[2m", "\033[1m", "\033[0m"]:
                plain = plain.replace(code, "")
            pad   = max(0, w - len(plain))
            line += raw + " " * pad + "  "
        print(line)
    blank()

def time_ago(ts: float) -> str:
    s = int(time.time() - ts)
    if s < 5:   return "just now"
    if s < 60:  return f"{s}s ago"
    if s < 3600: return f"{s//60}m ago"
    if s < 86400: return f"{s//3600}h ago"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

def fmt_addr(addr: str, n: int = 10) -> str:
    if len(addr) <= n * 2 + 3:
        return addr
    return addr[:n] + "…" + addr[-6:]

# ─── HTTP helpers ──────────────────────────────────────────────────────────
_NODE = "http://localhost:5000"

def _check_requests() -> None:
    if not _REQUESTS_OK:
        err("'requests' package not installed.  Run:  pip install requests")
        sys.exit(1)

def get(path: str, timeout: int = 10) -> dict:
    _check_requests()
    url = _NODE.rstrip("/") + path
    r   = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def post(path: str, data: dict, timeout: int = 30) -> dict:
    _check_requests()
    url = _NODE.rstrip("/") + path
    r   = requests.post(url, json=data, timeout=timeout)
    return r.status_code, r.json()

# ─── Command implementations ───────────────────────────────────────────────

def cmd_new(args) -> int:
    """Generate a fresh ECDSA wallet."""
    header("Generate New Wallet")
    blank()
    w = Wallet()

    kv("Address",    cyan(w.address))
    kv("Public Key", dim(w.get_public_key_hex()[:40] + "…"))
    blank()

    save_path = getattr(args, "save", None)
    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        w.save(save_path)
        ok(f"Private key saved  →  {bold(save_path)}")
        warn("Back up this file — it cannot be recovered if lost!")
    else:
        warn("No --save path given.  Key NOT persisted.")
        kv("Private Key PEM", "(not saved — pass --save <file>)")

    blank()
    return 0


def cmd_address(args) -> int:
    """Show address stored in a key file."""
    header("Wallet Address")
    blank()
    try:
        w = Wallet.load(args.key)
    except Exception as e:
        err(f"Cannot load key file '{args.key}': {e}")
        return 1

    kv("Key File",   dim(args.key))
    kv("Address",    cyan(w.address))
    kv("Public Key", dim(w.get_public_key_hex()[:50] + "…"))
    blank()
    return 0


def cmd_balance(args) -> int:
    """Query confirmed + available balance."""
    header("Balance Lookup")
    blank()
    addr = args.address
    kv("Address", cyan(addr))
    kv("Node",    dim(_NODE))
    blank()

    try:
        bal_data = get(f"/balance/{addr}")
    except Exception as e:
        err(f"Node unreachable: {e}")
        return 1

    confirmed = bal_data.get("balance", 0.0)

    # Try to get available (UTXO snapshot)
    available = None
    pending_out = 0.0
    try:
        utxo = get("/utxo")
        if addr in utxo:
            available   = utxo[addr]["available"]
            pending_out = utxo[addr]["pending_out"]
    except Exception:
        pass

    kv("Confirmed",  f"{cyan(f'{confirmed:.8f}')} DRN")
    if available is not None:
        kv("Pending out",  f"{yellow(f'{pending_out:.8f}')} DRN")
        kv("Available",    f"{green(f'{available:.8f}')} DRN  {dim('(spendable now)')}")
    blank()
    return 0


def cmd_send(args) -> int:
    """Sign and broadcast a transaction."""
    header("Send DRN")
    blank()

    # Load wallet
    try:
        w = Wallet.load(args.key)
    except Exception as e:
        err(f"Cannot load key file '{args.key}': {e}")
        return 1

    kv("From",   cyan(w.address))
    kv("To",     cyan(args.to))
    kv("Amount", f"{bold(str(args.amount))} DRN")
    fee_val  = float(getattr(args, "fee", 0.0) or 0.0)
    lock_val = int(getattr(args, "lock_until_block", 0) or 0)
    if fee_val:
        kv("Fee",  f"{yellow(str(fee_val))} DRN  {dim('(miner tip)')}")
    if lock_val:
        kv("Locked until", f"block {cyan(str(lock_val))}")
    kv("Node",   dim(_NODE))
    blank()

    # Confirm if interactive
    if not getattr(args, "yes", False) and sys.stdin.isatty():
        try:
            ans = input(f"  Confirm send? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans != "y":
            warn("Cancelled.")
            return 0
        blank()

    # Build + sign
    print(f"  {dim('Signing…')}", end="", flush=True)
    try:
        tx = w.create_transaction(
            recipient=args.to,
            amount=float(args.amount),
            fee=float(getattr(args, "fee", 0.0) or 0.0),
            lock_until_block=int(getattr(args, "lock_until_block", 0) or 0),
        )
    except Exception as e:
        print()
        err(f"Failed to sign: {e}")
        return 1
    print(f"  {green('done')}")

    # Broadcast
    print(f"  {dim('Broadcasting…')}", end="", flush=True)
    try:
        status, resp = post("/transactions/new", tx)
    except Exception as e:
        print()
        err(f"Cannot reach node: {e}")
        return 1
    print(f"  {green('done') if status == 201 else red('error')}")
    blank()

    if status == 201:
        ok("Transaction accepted!")
        blk_idx = resp.get("confirming_block", "?")
        kv("Confirms at", f"block {cyan(f'#{blk_idx}')}")
        kv("Mempool size", resp.get("mempool_size", "?"))
    else:
        err("Transaction rejected:")
        print(f"    {red(resp.get('error', 'Unknown error'))}")
        bal = resp.get("sender_balance")
        if bal is not None:
            kv("Sender balance", f"{bal:.8f} DRN")
        blank()
        return 1

    blank()
    return 0


def cmd_history(args) -> int:
    """Show transaction history for an address."""
    header("Transaction History")
    blank()
    addr  = args.address
    limit = getattr(args, "limit", 20)

    kv("Address", cyan(addr))
    kv("Node",    dim(_NODE))
    blank()

    try:
        data = get(f"/history/{addr}")
    except Exception as e:
        err(f"Node unreachable: {e}")
        return 1

    txns = data.get("transactions", [])
    if not txns:
        warn("No confirmed transactions found for this address.")
        blank()
        return 0

    txns = txns[:limit]
    section(f"{len(txns)} transaction(s)")

    rows = []
    for tx in txns:
        blk     = tx.get("block_index", "?")
        ts      = tx.get("block_time",  0)
        sender  = tx.get("sender",    "")
        recip   = tx.get("recipient", "")
        amt     = float(tx.get("amount", 0))

        if recip == addr:
            direction = green("↑ in ")
            peer      = fmt_addr(sender)
        else:
            direction = red("↓ out")
            peer      = fmt_addr(recip)

        rows.append([
            f"#{blk}",
            time_ago(ts),
            direction,
            peer,
            f"{cyan(f'{amt:.2f}')} DRN",
        ])

    table(
        ["Block", "Time", "Dir", "Counterparty", "Amount"],
        rows,
        [7, 12, 6, 26, 14],
    )
    return 0


def cmd_utxo(args) -> int:
    """Show all confirmed balances across the network."""
    header("Network UTXO Snapshot")
    blank()
    kv("Node", dim(_NODE))
    blank()

    try:
        data = get("/utxo")
    except Exception as e:
        err(f"Node unreachable: {e}")
        return 1

    if not data:
        warn("No addresses with confirmed balances yet.")
        blank()
        return 0

    # Sort by confirmed balance desc
    items = sorted(data.items(), key=lambda x: x[1]["confirmed"], reverse=True)

    rows = []
    total = 0.0
    for addr, info in items:
        conf = float(info["confirmed"])
        pout = float(info["pending_out"])
        avail = float(info["available"])
        total += conf
        rows.append([
            fmt_addr(addr, 14),
            f"{cyan(f'{conf:.4f}')}",
            f"{yellow(f'{pout:.4f}') if pout > 0 else dim('0.0000')}",
            f"{green(f'{avail:.4f}')}",
        ])

    table(
        ["Address", "Confirmed", "Pending-Out", "Available"],
        rows,
        [32, 12, 12, 12],
    )
    kv("Total DRN mined", f"{cyan(f'{total:.2f}')} DRN  {dim(f'({len(items)} addresses)')}")
    blank()
    return 0


def cmd_info(args) -> int:
    """Display live node and chain statistics."""
    header("Node Info")
    blank()
    kv("Node", dim(_NODE))
    blank()

    try:
        data = get("/")
    except Exception as e:
        err(f"Node unreachable: {e}")
        return 1

    section("Chain")
    kv("Node ID",      cyan(data.get("node_id", "?")))
    kv("Height",       bold(data.get("chain_height", "?")))
    kv("Difficulty",   data.get("difficulty", "?"))
    kv("Pending txns", data.get("pending_txns", 0))
    kv("Chain valid",  green("Yes") if data.get("chain_valid") else red("No"))
    kv("Peers",        ", ".join(data.get("peers", [])) or dim("none"))

    rt = data.get("retarget_status", {})
    if rt:
        section("Retarget")
        kv("Avg block time",  f"{rt.get('avg_block_time_s', '?')}s")
        kv("Target time",     f"{rt.get('target_block_time_s', '?')}s")
        kv("Next retarget at",f"block #{rt.get('next_retarget_at', '?')}")
        kv("Retargets done",  rt.get("retarget_count", 0))

    stor = data.get("storage", {})
    if stor:
        section("Storage")
        kv("DB path",    dim(stor.get("db_path", "?")))
        kv("DB size",    f"{stor.get('db_size_kb', '?')} KB")
        kv("Blocks",     stor.get("blocks_stored", "?"))
        kv("Txns in DB", stor.get("txns_stored", "?"))

    blank()
    return 0


def cmd_blocks(args) -> int:
    """List recent blocks."""
    count = getattr(args, "count", 10)
    header(f"Recent Blocks  (last {count})")
    blank()
    kv("Node", dim(_NODE))
    blank()

    try:
        data = get("/chain")
    except Exception as e:
        err(f"Node unreachable: {e}")
        return 1

    chain = data.get("chain", [])
    if not chain:
        warn("Chain is empty.")
        blank()
        return 0

    recent = list(reversed(chain))[:count]

    rows = []
    for b in recent:
        idx    = b.get("index", "?")
        ts     = b.get("timestamp", 0)
        h      = b.get("hash", "")
        diff   = b.get("difficulty", "?")
        nonce  = b.get("nonce", "?")
        txcount = len(b.get("transactions", []))
        rows.append([
            cyan(f"#{idx}"),
            time_ago(ts),
            dim(h[:12] + "…"),
            str(txcount),
            str(diff),
            str(nonce),
        ])

    table(
        ["Block", "Time", "Hash", "Txns", "Diff", "Nonce"],
        rows,
        [7, 12, 15, 5, 5, 10],
    )
    return 0


def cmd_mine(args) -> int:
    """Trigger Proof-of-Work mining on the node."""
    header("Mine Block")
    blank()
    kv("Node", dim(_NODE))

    miner_addr = getattr(args, "miner", None) or ""
    if miner_addr:
        kv("Miner address", cyan(miner_addr))
    blank()

    print(f"  {dim('Mining (this may take a few seconds)…')}", flush=True)
    t0 = time.time()

    path = f"/mine?miner={miner_addr}" if miner_addr else "/mine"
    try:
        data = get(path, timeout=120)
    except Exception as e:
        err(f"Mining failed: {e}")
        return 1

    elapsed = time.time() - t0
    blank()
    ok(f"Block mined in {elapsed:.2f}s!")

    blk = data.get("block", {})
    reward_to = data.get("miner_address", miner_addr or "?")
    new_bal   = data.get("miner_balance", "?")
    kv("Block index",  cyan(f"#{blk.get('index', '?')}"))
    kv("Hash",         dim(blk.get("hash", "?")[:48] + "…"))
    kv("Nonce",        blk.get("nonce", "?"))
    kv("Difficulty",   blk.get("difficulty", "?"))
    kv("Block reward", f"{cyan(str(data.get('block_reward', 50)))} DRN")
    kv("Reward to",    fmt_addr(reward_to, 14))
    kv("New balance",  f"{cyan(str(round(float(new_bal), 4)))} DRN" if new_bal != "?" else "?")
    blank()
    return 0


# ─── CLI entry point ───────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="drn_wallet",
        description="DorianCoin (DRN) CLI Wallet — Stage 8",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python drn_wallet.py new --save keys/alice.pem
  python drn_wallet.py balance DRN1Alice...
  python drn_wallet.py send --key keys/alice.pem --to DRN1Bob... --amount 10
  python drn_wallet.py history DRN1Alice... --limit 10
  python drn_wallet.py utxo
  python drn_wallet.py info
  python drn_wallet.py blocks --count 5
  python drn_wallet.py mine
""",
    )
    p.add_argument("--node",     default="http://localhost:5000",
                   help="Node base URL (default: http://localhost:5000)")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI colour output")

    sub = p.add_subparsers(dest="command", metavar="command")

    # new
    sp = sub.add_parser("new", help="Generate a new wallet")
    sp.add_argument("--save", metavar="FILE",
                    help="Path to save the private key PEM  (e.g. keys/alice.pem)")

    # address
    sp = sub.add_parser("address", help="Show address from a key file")
    sp.add_argument("key", metavar="KEYFILE", help="Path to PEM key file")

    # balance
    sp = sub.add_parser("balance", help="Check balance for an address")
    sp.add_argument("address", metavar="ADDRESS", help="DRN address to look up")

    # send
    sp = sub.add_parser("send", help="Sign and broadcast a transaction")
    sp.add_argument("--key",    required=True, metavar="KEYFILE",
                    help="Sender private key PEM file")
    sp.add_argument("--to",     required=True, metavar="ADDRESS",
                    help="Recipient DRN address")
    sp.add_argument("--amount", required=True, type=float, metavar="DRN",
                    help="Amount to send (in DRN)")
    sp.add_argument("--fee",    type=float, default=0.0, metavar="DRN",
                    help="Miner tip in DRN (default 0 -- free tx, lower priority)")
    sp.add_argument("--lock-until-block", type=int, default=0, metavar="N",
                    help="Time-lock: tx stays pending until block N is mined")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="Skip confirmation prompt")

    # history
    sp = sub.add_parser("history", help="Show transaction history")
    sp.add_argument("address", metavar="ADDRESS", help="DRN address")
    sp.add_argument("--limit", type=int, default=20, metavar="N",
                    help="Max transactions to show (default: 20)")

    # utxo
    sub.add_parser("utxo", help="Show all confirmed balances on the network")

    # info
    sub.add_parser("info", help="Show live node and chain statistics")

    # blocks
    sp = sub.add_parser("blocks", help="List recent blocks")
    sp.add_argument("--count", type=int, default=10, metavar="N",
                    help="Number of recent blocks to show (default: 10)")

    # mine
    sp = sub.add_parser("mine", help="Trigger mining on the node")
    sp.add_argument("--miner", metavar="ADDRESS",
                    help="DRN address to receive the block reward (default: node's own wallet)")

    return p


def main(argv=None) -> int:
    global _COLOR, _NODE

    parser = build_parser()
    args   = parser.parse_args(argv)

    # Apply global flags
    if getattr(args, "no_color", False):
        _COLOR = False
    if getattr(args, "node", None):
        _NODE = args.node.rstrip("/")

    # Windows ANSI enable
    if _COLOR and sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32           # type: ignore
            kernel32.SetConsoleMode(
                kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            pass

    commands = {
        "new":     cmd_new,
        "address": cmd_address,
        "balance": cmd_balance,
        "send":    cmd_send,
        "history": cmd_history,
        "utxo":    cmd_utxo,
        "info":    cmd_info,
        "blocks":  cmd_blocks,
        "mine":    cmd_mine,
    }

    if not args.command:
        # Print friendly usage when no command given
        print(f"\n  {bold('DorianCoin CLI Wallet')}  {dim('(DRN)')}")
        print(f"\n  {dim('Commands:')}")
        for name in commands:
            print(f"    {cyan(name.ljust(10))} {parser._subparsers._actions[1].choices[name].description or ''}")
        print(f"\n  {dim('Run:  python drn_wallet.py --help  for full usage')}")
        blank()
        return 0

    fn = commands.get(args.command)
    if not fn:
        err(f"Unknown command: {args.command}")
        return 1

    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
