"""
storage.py -- DorianCoin (DRN) Persistent Storage Layer  (Stage 5)
===================================================================
SQLite-backed persistence for the blockchain.  The node survives
restarts without re-mining — the full chain is loaded from disk on
every startup.

Schema
------
  blocks        -- one row per block (header + hash)
  transactions  -- one row per transaction, FK -> blocks
  node_meta     -- key/value store for difficulty, retarget config, etc.

Indexes
-------
  idx_txns_block      -- fast per-block tx lookup
  idx_txns_recipient  -- fast balance / history queries on recipient
  idx_txns_sender     -- fast balance / history queries on sender

Usage
-----
    from storage import BlockchainStorage
    storage = BlockchainStorage("data/chain_5000.db")
    bc = Blockchain(storage=storage)   # loads existing chain or mines genesis
"""

import json
import os
import sqlite3
import threading
from typing import Optional


class BlockchainStorage:
    """SQLite persistence for a single DorianCoin node.

    Thread safety
    -------------
    Uses a per-thread connection pool so Flask's threaded=True mode
    can call save_block() concurrently from different request threads.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS blocks (
        block_index   INTEGER PRIMARY KEY,
        timestamp     REAL    NOT NULL,
        previous_hash TEXT    NOT NULL,
        nonce         INTEGER NOT NULL,
        difficulty    INTEGER NOT NULL,
        hash          TEXT    NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        block_index INTEGER NOT NULL REFERENCES blocks(block_index),
        tx_json     TEXT    NOT NULL,
        sender      TEXT    NOT NULL,
        recipient   TEXT    NOT NULL,
        amount      REAL    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS node_meta (
        key     TEXT PRIMARY KEY,
        value   TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_txns_block
        ON transactions(block_index);
    CREATE INDEX IF NOT EXISTS idx_txns_recipient
        ON transactions(recipient);
    CREATE INDEX IF NOT EXISTS idx_txns_sender
        ON transactions(sender);
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

        # Make sure the data/ directory exists
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._local = threading.local()   # per-thread connection cache
        self._init_schema()

    # ------------------------------------------------------------------
    # Connection management (one connection per thread)
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Return the current thread's SQLite connection, creating it if needed."""
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")    # write-ahead log for concurrency
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")  # balanced durability/speed
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        self._conn().executescript(self.SCHEMA)
        self._conn().commit()

    # ------------------------------------------------------------------
    # Block persistence
    # ------------------------------------------------------------------

    def save_block(self, block) -> None:
        """Persist a Block object and all its transactions atomically.

        Transactions are stored as full JSON blobs so the exact dict
        structure is preserved — this is critical for hash reproducibility
        on reload (calculate_hash() is sensitive to key ordering / types).

        Uses INSERT OR IGNORE so re-saving the same block is safe.
        """
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO blocks
                       (block_index, timestamp, previous_hash, nonce, difficulty, hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (block.index, block.timestamp, block.previous_hash,
                 block.nonce, block.difficulty, block.hash),
            )
            for tx in block.transactions:
                conn.execute(
                    """INSERT INTO transactions
                           (block_index, tx_json, sender, recipient, amount)
                       VALUES (?, ?, ?, ?, ?)""",
                    (block.index,
                     json.dumps(tx, sort_keys=True),
                     tx.get("sender",    ""),
                     tx.get("recipient", ""),
                     float(tx.get("amount", 0))),
                )

    def save_chain(self, blocks) -> None:
        """Persist an entire list of Block objects (used after P2P chain replace)."""
        # Clear existing data first, then re-insert
        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM blocks")
        for block in blocks:
            self.save_block(block)

    # ------------------------------------------------------------------
    # Chain loading
    # ------------------------------------------------------------------

    def load_chain(self) -> list:
        """Return every block as an ordered list of plain dicts.

        Each dict has the same keys as Block.to_dict() so it can be
        passed directly to Block.from_dict() for reconstruction.
        Transactions are deserialized from their stored JSON blob so
        the exact original structure is preserved.
        """
        conn  = self._conn()
        rows  = conn.execute(
            "SELECT * FROM blocks ORDER BY block_index"
        ).fetchall()

        chain = []
        for row in rows:
            b = dict(row)
            b["index"] = b.pop("block_index")

            tx_rows = conn.execute(
                """SELECT tx_json FROM transactions
                   WHERE block_index = ?
                   ORDER BY id""",
                (b["index"],),
            ).fetchall()
            b["transactions"] = [json.loads(r[0]) for r in tx_rows]

            chain.append(b)
        return chain

    def has_chain(self) -> bool:
        """Return True if there is at least one block saved."""
        row = self._conn().execute("SELECT COUNT(*) FROM blocks").fetchone()
        return row[0] > 0

    def block_count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM blocks").fetchone()[0]

    # ------------------------------------------------------------------
    # Balance queries  (direct SQL — faster than scanning Block objects)
    # ------------------------------------------------------------------

    def get_balance(self, address: str) -> float:
        """Calculate confirmed DRN balance for an address using SQL aggregation."""
        conn = self._conn()
        received = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE recipient = ?",
            (address,),
        ).fetchone()[0]
        sent = conn.execute(
            """SELECT COALESCE(SUM(amount), 0)
               FROM transactions
               WHERE sender = ? AND sender != 'NETWORK'""",
            (address,),
        ).fetchone()[0]
        return float(received) - float(sent)

    def get_address_history(self, address: str, limit: int = 50) -> list:
        """Return the last `limit` transactions involving `address`."""
        rows = self._conn().execute(
            """SELECT t.sender, t.recipient, t.amount,
                      b.block_index, b.timestamp AS block_time
               FROM   transactions t
               JOIN   blocks       b ON b.block_index = t.block_index
               WHERE  t.sender = ? OR t.recipient = ?
               ORDER  BY b.block_index DESC, t.id DESC
               LIMIT  ?""",
            (address, address, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Node metadata  (difficulty, retarget config, etc.)
    # ------------------------------------------------------------------

    def save_meta(self, key: str, value) -> None:
        """Upsert a key/value pair. Value is JSON-encoded."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO node_meta (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def load_meta(self, key: str, default=None):
        """Retrieve and JSON-decode a stored value, or return default."""
        row = self._conn().execute(
            "SELECT value FROM node_meta WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def load_all_meta(self) -> dict:
        rows = self._conn().execute("SELECT key, value FROM node_meta").fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}

    # ------------------------------------------------------------------
    # Introspection / stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return storage statistics for the /storage API endpoint."""
        conn    = self._conn()
        blocks  = self.block_count()
        txns    = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        size_b  = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        latest  = conn.execute(
            "SELECT hash, timestamp FROM blocks ORDER BY block_index DESC LIMIT 1"
        ).fetchone()
        return {
            "db_path":       self.db_path,
            "db_size_kb":    round(size_b / 1024, 2),
            "blocks_stored": blocks,
            "txns_stored":   int(txns),
            "chain_tip":     dict(latest) if latest else None,
        }

    def close(self) -> None:
        if getattr(self._local, "conn", None):
            self._local.conn.close()
            self._local.conn = None
