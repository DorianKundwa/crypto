"""
node.py — DorianCoin (DRN) Flask REST Node
==========================================
Stage 3: HTTP API + Nakamoto-style peer-to-peer consensus.

Endpoints
---------
GET  /                       Node info (id, miner address, height, peers)
GET  /chain                  Full blockchain as JSON
GET  /chain/valid            Is our chain valid?
POST /transactions/new       Submit a signed transaction
GET  /transactions/pending   List pending (unconfirmed) transactions
GET  /mine                   Mine a block (PoW) and claim the reward
GET  /balance/<address>      DRN balance for any address
GET  /wallet/new             Generate a fresh wallet
POST /nodes/register         Register one or more peer nodes
GET  /nodes                  List known peer nodes
GET  /nodes/resolve          Run consensus: adopt longest valid peer chain

Usage
-----
# Terminal 1
python node.py --port 5000

# Terminal 2
python node.py --port 5001

# Register each other
curl -X POST http://localhost:5000/nodes/register \\
     -H "Content-Type: application/json" \\
     -d '{"nodes": ["localhost:5001"]}'

# Mine on node 5000
curl http://localhost:5000/mine

# Sync node 5001
curl http://localhost:5001/nodes/resolve
"""

import argparse
import uuid
import os
import sys
import threading
import requests
from flask import Flask, jsonify, request, send_file, make_response

from blockchain import Blockchain, Block
from wallet import Wallet
from storage import BlockchainStorage

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False   # preserve insertion order in responses


@app.after_request
def _add_cors(response):
    """Allow the Block Explorer (any origin) to call our API."""
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# ---------------------------------------------------------------------------
# Global state  (populated in __main__ before app.run())
# ---------------------------------------------------------------------------

NODE_ID: str              = str(uuid.uuid4()).replace("-", "")[:12]
blockchain: Blockchain    = None   # type: ignore  # set after Flask starts
miner_wallet: Wallet      = None   # type: ignore  # set after Flask starts
node_storage              = None   # type: ignore  # BlockchainStorage, set after Flask starts
peer_nodes: set           = set()  # "host:port" strings (no http://)
_node_ready: bool         = False  # True once genesis block is mined

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _chain_json() -> list:
    """Serialise every block in the chain to a list of plain dicts."""
    return [b.to_dict() for b in blockchain.chain]


def _push_tx_to_peers(tx: dict) -> None:
    """Forward a new transaction to all registered peers (best-effort)."""
    for addr in list(peer_nodes):
        try:
            requests.post(
                f"http://{addr}/transactions/new",
                json=tx,
                timeout=3,
            )
        except requests.RequestException:
            pass


def _pull_resolve_from_peers() -> bool:
    """Ask all peers to pull-resolve after we mine a block.

    Each peer calls GET /nodes/resolve on itself, which triggers it to
    pull our (now-longer) chain.  This is simpler than pushing blocks.
    """
    for addr in list(peer_nodes):
        try:
            requests.get(f"http://{addr}/nodes/resolve", timeout=5)
        except requests.RequestException:
            pass
    return True


def _run_consensus() -> bool:
    """Pull chains from all peers.  Replace ours if a longer valid one exists.

    Implements simplified Nakamoto consensus: the longest valid chain wins.
    Returns True if our chain was replaced, False if ours is already longest.
    """
    best_length    = blockchain.height
    best_chain_data = None

    for addr in list(peer_nodes):
        try:
            resp = requests.get(f"http://{addr}/chain", timeout=5)
            if resp.status_code != 200:
                continue
            data         = resp.json()
            their_length = data.get("length", 0)
            their_chain  = data.get("chain",  [])

            if their_length > best_length and Blockchain.valid_chain_data(their_chain):
                best_length    = their_length
                best_chain_data = their_chain

        except requests.RequestException:
            continue   # peer is unreachable — skip

    if best_chain_data:
        blockchain.load_chain_from_data(best_chain_data)
        return True
    return False


# ---------------------------------------------------------------------------
# Routes — Node info
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    """Quick health-check / summary for this node.

    Returns HTTP 503 while genesis block is still being mined so that
    the p2p_demo readiness-poll can distinguish 'not bound yet' from
    'bound but initialising'.
    """
    if not _node_ready:
        return jsonify({"status": "initialising", "node_id": NODE_ID}), 503
    resp = {
        "node_id":          NODE_ID,
        "miner_address":    miner_wallet.address,
        "chain_height":     blockchain.height,
        "difficulty":       blockchain.difficulty,
        "pending_txns":     len(blockchain.pending_transactions),
        "peers":            list(peer_nodes),
        "chain_valid":      blockchain.is_valid(),
        "retarget_status":  blockchain.retarget_status(),
    }
    if node_storage:
        resp["storage"] = node_storage.stats()
    return jsonify(resp)


# ---------------------------------------------------------------------------
# Routes — Blockchain
# ---------------------------------------------------------------------------

@app.route("/chain", methods=["GET"])
def get_chain():
    """Return the full blockchain serialised as JSON."""
    return jsonify({
        "chain":  _chain_json(),
        "length": blockchain.height,
    })


@app.route("/chain/valid", methods=["GET"])
def chain_valid():
    """Return whether our chain passes all integrity checks."""
    return jsonify({
        "valid":  blockchain.is_valid(),
        "height": blockchain.height,
    })


# ---------------------------------------------------------------------------
# Routes — Transactions
# ---------------------------------------------------------------------------

@app.route("/transactions/pending", methods=["GET"])
def pending_transactions():
    """List all transactions waiting to be included in the next block."""
    return jsonify({
        "pending": blockchain.pending_transactions,
        "count":   len(blockchain.pending_transactions),
    })


@app.route("/transactions/new", methods=["POST"])
def new_transaction():
    """Accept and buffer a signed transaction.

    Expected JSON body::

        {
            "sender":     "DRN1...",
            "recipient":  "DRN1...",
            "amount":     10.0,
            "public_key": "04ab...",
            "signature":  "3045..."
        }

    Stage 2: Verifies the ECDSA signature before accepting.
    Stage 7: Verifies sender has sufficient funds (confirmed minus
             any already-pending outgoing) and rejects double-spends.
    """
    tx = request.get_json(silent=True)
    if not tx:
        return jsonify({"error": "No valid JSON body provided."}), 400

    required = {"sender", "recipient", "amount", "public_key", "signature"}
    missing  = required - set(tx.keys())
    if missing:
        return jsonify({"error": f"Missing required fields: {sorted(missing)}"}), 400

    try:
        confirming_block = blockchain.add_transaction(tx)
    except ValueError as exc:
        # Stage 7: enrich the rejection with current balance info
        sender = tx.get("sender", "")
        confirmed_bal  = blockchain.get_balance(sender) if sender else None
        return jsonify({
            "error":             str(exc),
            "sender_balance":    confirmed_bal,
            "pending_in_mempool": len(blockchain.pending_transactions),
        }), 400

    # Broadcast to peers only if this came from a client (not a peer relay)
    if not tx.get("_relayed"):
        tx["_relayed"] = True
        _push_tx_to_peers(tx)

    return jsonify({
        "message":          "Transaction accepted.",
        "confirming_block": confirming_block,
        "sender":           tx["sender"],
        "recipient":        tx["recipient"],
        "amount":           tx["amount"],
        "mempool_size":     len(blockchain.pending_transactions),
    }), 201


@app.route("/utxo", methods=["GET"])
def get_utxo():
    """Return a full balance snapshot of every address on the chain.

    Stage 7 — each entry shows:
      confirmed   -- on-chain balance (all mined blocks)
      pending_out -- total outgoing in the current mempool
      available   -- spendable right now  (confirmed - pending_out)

    Example response::

        {
          "DRN1Alice...": {"confirmed": 250.0, "pending_out": 10.0, "available": 240.0},
          "DRN1Bob..":   {"confirmed":  10.0, "pending_out":  0.0, "available":  10.0}
        }
    """
    if not _node_ready:
        return jsonify({"status": "initialising"}), 503
    return jsonify(blockchain.get_utxo_snapshot())



# ---------------------------------------------------------------------------
# Routes — Mining
# ---------------------------------------------------------------------------

@app.route("/mine", methods=["GET"])
def mine():
    """Run Proof-of-Work on pending transactions and claim the block reward.

    This endpoint blocks until the hash target is found (difficulty=4 is
    a few seconds max).  Notifies all peers to pull-resolve after success.
    """
    new_block = blockchain.mine_pending_transactions(miner_wallet.address)

    # Ask peers to sync  (they'll call /nodes/resolve on themselves)
    _pull_resolve_from_peers()

    resp = {
        "message":         f"Block {new_block.index} mined successfully!",
        "block":            new_block.to_dict(),
        "miner":            miner_wallet.address,
        "block_reward":     Blockchain.BLOCK_REWARD,
        "miner_balance":    blockchain.get_balance(miner_wallet.address),
        "difficulty":       blockchain.difficulty,
    }
    # Include retarget info if one just fired
    if blockchain.retarget_log:
        resp["last_retarget"] = blockchain.retarget_log[-1]
    return jsonify(resp)


# ---------------------------------------------------------------------------
# Routes — Balance
# ---------------------------------------------------------------------------

@app.route("/balance/<address>", methods=["GET"])
def get_balance(address: str):
    """Return the confirmed DRN balance for any address."""
    balance = blockchain.get_balance(address)
    return jsonify({
        "address": address,
        "balance": balance,
        "unit":    "DRN",
    })


@app.route("/difficulty", methods=["GET"])
def get_difficulty():
    """Return full retarget status including difficulty history.

    Useful for monitoring how difficulty evolves over time.
    """
    return jsonify(blockchain.retarget_status())


@app.route("/storage", methods=["GET"])
def get_storage():
    """Return SQLite storage statistics for this node."""
    if not node_storage:
        return jsonify({"message": "No persistent storage configured."}), 404
    return jsonify(node_storage.stats())


@app.route("/history/<address>", methods=["GET"])
def get_history(address: str):
    """Return the last 50 confirmed transactions for an address.

    Uses the indexed SQL query in BlockchainStorage for O(log n) speed.
    Falls back to scanning the in-memory chain when no storage is attached.
    """
    if node_storage:
        history = node_storage.get_address_history(address, limit=50)
    else:
        history = [
            dict(tx, block_index=b.index, block_time=b.timestamp)
            for b in blockchain.chain
            for tx in b.transactions
            if tx.get("sender") == address or tx.get("recipient") == address
        ][-50:]
    return jsonify({"address": address, "count": len(history), "transactions": history})



# ---------------------------------------------------------------------------
# Routes — Block Explorer (Stage 6)
# ---------------------------------------------------------------------------

@app.route("/explorer", methods=["GET"])
def explorer():
    """Serve the DorianCoin Block Explorer web UI.

    The HTML file lives next to node.py so relative API calls (e.g. /chain)
    hit the same origin -- no proxy or CORS workarounds needed.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return send_file(os.path.join(here, "explorer.html"))


@app.route("/wallet/new", methods=["GET"])
def new_wallet():
    """Generate a fresh ECDSA wallet.

    Returns the public address and public key.
    Private key is saved to data/<short_address>.pem — back it up!
    """
    w = Wallet()
    short = w.address[3:15]   # 12 chars after 'DRN' prefix
    pem_path = os.path.join("data", f"{short}.pem")
    w.save(pem_path)
    return jsonify({
        "address":    w.address,
        "public_key": w.get_public_key_hex(),
        "pem_file":   pem_path,
        "warning":    "Back up the PEM file! It holds your private key.",
    })


# ---------------------------------------------------------------------------
# Routes — Peer nodes
# ---------------------------------------------------------------------------

@app.route("/nodes", methods=["GET"])
def get_nodes():
    """List all registered peer nodes."""
    return jsonify({
        "nodes": sorted(peer_nodes),
        "count": len(peer_nodes),
    })


@app.route("/nodes/register", methods=["POST"])
def register_nodes():
    """Register one or more peer node addresses.

    Expected JSON body::

        { "nodes": ["localhost:5001", "localhost:5002"] }

    Addresses should be host:port strings (without http://).
    """
    data = request.get_json(silent=True)
    if not data or "nodes" not in data:
        return jsonify({
            "error": 'Provide {"nodes": ["host:port", ...]} in the request body.'
        }), 400

    added = []
    for raw in data["nodes"]:
        addr = raw.strip().lstrip("http://").rstrip("/")
        if addr:
            peer_nodes.add(addr)
            added.append(addr)

    return jsonify({
        "message":     f"Registered {len(added)} peer(s).",
        "added":        added,
        "all_peers":    sorted(peer_nodes),
    }), 201


@app.route("/nodes/resolve", methods=["GET"])
def resolve():
    """Run Nakamoto consensus: adopt the longest valid chain from peers.

    Returns a message indicating whether the chain was replaced, and
    the current chain afterwards.
    """
    replaced = _run_consensus()
    if replaced:
        msg = "Chain replaced with a longer valid peer chain."
    else:
        msg = "Our chain is authoritative (longest valid chain)."

    return jsonify({
        "message":      msg,
        "replaced":     replaced,
        "chain_height": blockchain.height,
        "chain":        _chain_json(),
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DorianCoin (DRN) Flask Node",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port",             type=int,   default=5000,
                        help="TCP port to listen on")
    parser.add_argument("--difficulty",        type=int,   default=4,
                        help="Starting PoW difficulty (leading zeros)")
    parser.add_argument("--retarget-interval", type=int,   default=10,
                        help="Retarget difficulty every N blocks")
    parser.add_argument("--target-block-time", type=float, default=10.0,
                        help="Target seconds per block for retargeting")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Initialise blockchain + wallet in a background thread so that
    # Flask can bind the port FIRST (genesis mining can take a few
    # seconds, and the p2p_demo polls / until it gets HTTP 200).
    # ------------------------------------------------------------------
    _init_port             = args.port
    _init_difficulty       = args.difficulty
    _init_retarget_interval = args.retarget_interval
    _init_target_block_time = args.target_block_time

    def _init_node() -> None:
        global blockchain, miner_wallet, node_storage, _node_ready

        os.makedirs("data", exist_ok=True)

        # Stage 5: open (or create) the node's SQLite database
        db_path      = os.path.join("data", f"chain_{_init_port}.db")
        node_storage = BlockchainStorage(db_path)

        blockchain = Blockchain(
            difficulty        = _init_difficulty,
            retarget_interval = _init_retarget_interval,
            target_block_time = _init_target_block_time,
            storage           = node_storage,
        )

        # Load or generate the miner wallet
        miner_key_path = os.path.join("data", f"miner_{_init_port}.pem")
        if os.path.exists(miner_key_path):
            miner_wallet = Wallet.load(miner_key_path)
            print(f"[Wallet] Loaded miner wallet from {miner_key_path}")
        else:
            miner_wallet = Wallet()
            miner_wallet.save(miner_key_path)
            print(f"[Wallet] New miner wallet saved to {miner_key_path}")

        stats = node_storage.stats()
        print()
        print("=" * 58)
        print(f"  DorianCoin Node  [{NODE_ID}]  READY")
        print("=" * 58)
        print(f"  Miner address : {miner_wallet.address}")
        print(f"  Chain height  : {blockchain.height}")
        print(f"  Difficulty    : {blockchain.difficulty}")
        print(f"  DB            : {stats['db_path']}  ({stats['db_size_kb']} KB)")
        print(f"  Blocks in DB  : {stats['blocks_stored']}")
        print()
        _node_ready = True

    init_thread = threading.Thread(target=_init_node, daemon=True)

    # ------------------------------------------------------------------
    # Banner (printed before Flask takes over stdout)
    # ------------------------------------------------------------------
    print()
    print("=" * 58)
    print(f"  DorianCoin Node  [{NODE_ID}]  starting...")
    print("=" * 58)
    print(f"  URL           : http://localhost:{args.port}")
    print(f"  Difficulty    : {args.difficulty} leading zeros")
    print(f"  Block reward  : {Blockchain.BLOCK_REWARD} DRN")
    print("=" * 58)
    print()
    print("  Endpoints:")
    print(f"    GET  http://localhost:{args.port}/explorer   <-- Block Explorer UI")
    print(f"    GET  http://localhost:{args.port}/")
    print(f"    GET  http://localhost:{args.port}/chain")
    print(f"    GET  http://localhost:{args.port}/mine")
    print(f"    GET  http://localhost:{args.port}/difficulty")
    print(f"    GET  http://localhost:{args.port}/storage")
    print(f"    GET  http://localhost:{args.port}/utxo")
    print(f"    POST http://localhost:{args.port}/transactions/new")
    print(f"    GET  http://localhost:{args.port}/transactions/pending")
    print(f"    GET  http://localhost:{args.port}/balance/<address>")
    print(f"    GET  http://localhost:{args.port}/history/<address>")
    print(f"    POST http://localhost:{args.port}/nodes/register")
    print(f"    GET  http://localhost:{args.port}/nodes/resolve")
    print()

    # ------------------------------------------------------------------
    # Start Flask FIRST (binds the port), then kick off init thread
    # ------------------------------------------------------------------
    init_thread.start()
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
