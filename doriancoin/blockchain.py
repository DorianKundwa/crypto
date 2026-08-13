"""
blockchain.py -- DorianCoin (DRN) Core Blockchain Engine
=========================================================
Stage 1: Block structure, SHA-256 hashing, Proof-of-Work, chain validation.
Stage 2: ECDSA signature verification on every incoming transaction.
Stage 3: Peer chain validation + load from JSON (for REST node consensus).
Stage 4: Automatic difficulty retargeting every N blocks.
Stage 5: Persistent SQLite storage -- chain survives node restarts.
Stage 6: Block Explorer served from node.py GET /explorer.
Stage 7: UTXO balance tracking + double-spend protection.
Stage 9: Fee-based mempool prioritisation + timelock + multi-sig dispatch.
"""

import hashlib
import json
import time
from typing import Optional

# Wallet is imported lazily inside add_transaction to avoid any potential
# circular-import issues when node.py later imports both modules.
# (wallet.py never imports blockchain.py, so a top-level import is also safe.)
from wallet import Wallet

# UTXOState provides balance validation and double-spend detection (Stage 7).
try:
    from utxo import UTXOState
except ImportError:
    UTXOState = None   # type: ignore

# BlockchainStorage is optional — only imported when a DB path is supplied.
try:
    from storage import BlockchainStorage
except ImportError:
    BlockchainStorage = None   # type: ignore


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------

class Block:
    """A single block in the DorianCoin blockchain.

    Attributes
    ----------
    index           : Position in the chain (0 = genesis).
    timestamp       : UNIX time the block object was created.
    transactions    : List of transaction dicts included in this block.
    previous_hash   : Hash of the preceding block (links the chain).
    nonce           : Counter incremented during Proof-of-Work mining.
    difficulty      : Number of leading zeros required in the block hash.
    hash            : Final SHA-256 hash — set after mine() completes.
    """

    def __init__(self, index: int, transactions: list,
                 previous_hash: str, difficulty: int = 4):
        self.index = index
        self.timestamp = time.time()
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = 0
        self.difficulty = difficulty
        self.hash: str | None = None

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def calculate_hash(self) -> str:
        """Return the SHA-256 hex-digest of the block's canonical data.

        The timestamp is intentionally excluded from the nonce loop so
        that two miners working in parallel on the same block produce
        different hash sequences (they started at different real times).
        The timestamp is locked-in when mine() is called and never
        mutated again, giving a deterministic result for validation.
        """
        block_data = {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "transactions":  self.transactions,
            "previous_hash": self.previous_hash,
            "nonce":         self.nonce,
        }
        encoded = json.dumps(block_data, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    # ------------------------------------------------------------------
    # Proof-of-Work
    # ------------------------------------------------------------------

    def mine(self) -> None:
        """Increment nonce until the block hash starts with `difficulty`
        leading zeros — the core Proof-of-Work loop.

        Bitcoin calls the target "nBits"; we keep it simple here and use
        a fixed leading-zero count. Difficulty retargeting will be added
        in Stage 4.
        """
        target = "0" * self.difficulty
        while True:
            self.hash = self.calculate_hash()
            if self.hash.startswith(target):
                return          # valid hash found → stop
            self.nonce += 1

    # ------------------------------------------------------------------
    # Serialisation helpers (used by the REST node later)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain-dict representation of the block."""
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "transactions":  self.transactions,
            "previous_hash": self.previous_hash,
            "nonce":         self.nonce,
            "difficulty":    self.difficulty,
            "hash":          self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Block":
        """Reconstruct a Block from a plain dict (e.g. from a peer's JSON).

        The resulting block has its hash and nonce already set — it is NOT
        re-mined.  Used by Blockchain.load_chain_from_data() and
        Blockchain.valid_chain_data().
        """
        block = cls(
            index=data["index"],
            transactions=data["transactions"],
            previous_hash=data["previous_hash"],
            difficulty=data["difficulty"],
        )
        block.timestamp = data["timestamp"]
        block.nonce     = data["nonce"]
        block.hash      = data["hash"]
        return block


# ---------------------------------------------------------------------------
# Blockchain
# ---------------------------------------------------------------------------

class Blockchain:
    """The DorianCoin chain — an ordered list of Blocks.

    Responsibilities:
      - Create and hold the genesis block.
      - Buffer incoming transactions until a block is mined.
      - Mine a new block (Proof-of-Work) and append it to the chain.
      - Validate the integrity of the whole chain.
      - Query the DRN balance of any address.
      - Accept / validate a peer chain received over the network (Stage 3).
    """

    # ------------------------------------------------------------------
    # Class-level constants
    # ------------------------------------------------------------------

    # Block reward paid to the miner (like Bitcoin's coinbase tx).
    BLOCK_REWARD: int = 50
    MAX_TXNS_PER_BLOCK = 10      # Stage 9A: cap on user txns per block

    def __init__(
        self,
        difficulty:        int   = 4,
        retarget_interval: int   = 10,
        target_block_time: float = 10.0,
        min_difficulty:    int   = 1,
        max_difficulty:    int   = 8,
        storage                  = None,   # Optional[BlockchainStorage]
    ):
        """Create a new blockchain, optionally backed by persistent storage.

        Parameters
        ----------
        difficulty          Starting PoW difficulty (leading zeros in hash).
        retarget_interval   Retarget every this many blocks (Bitcoin: 2016).
        target_block_time   Desired seconds per block   (Bitcoin: 600).
        min_difficulty      Floor for automatic retargeting.
        max_difficulty      Ceiling for automatic retargeting.
        storage             Optional BlockchainStorage instance.  When
                            provided the chain is loaded from (or saved to)
                            the SQLite database on every mine.
        """
        self.difficulty         = difficulty
        self.retarget_interval  = retarget_interval
        self.target_block_time  = target_block_time
        self.min_difficulty     = min_difficulty
        self.max_difficulty     = max_difficulty
        self.storage            = storage

        self.pending_transactions: list = []
        self.retarget_log: list         = []   # history of every retarget event

        # ----------------------------------------------------------
        # Stage 5: restore from DB if we have a saved chain
        # ----------------------------------------------------------
        if storage and storage.has_chain():
            print("[Storage] Loading chain from database...")
            self.chain = self._load_from_storage()

            # Restore difficulty + retarget settings that were saved last
            saved_diff = storage.load_meta("difficulty", difficulty)
            saved_ri   = storage.load_meta("retarget_interval", retarget_interval)
            saved_tbt  = storage.load_meta("target_block_time", target_block_time)
            self.difficulty        = saved_diff
            self.retarget_interval = saved_ri
            self.target_block_time = saved_tbt

            print(f"[Storage] Restored {len(self.chain)} block(s)  "
                  f"difficulty={self.difficulty}")
        else:
            # Fresh start -- mine genesis and immediately persist it
            genesis     = self._create_genesis_block()
            self.chain  = [genesis]
            if storage:
                storage.save_block(genesis)
                self._save_meta_to_storage()
                print(f"[Storage] Genesis saved to {storage.db_path}")

    def _load_from_storage(self) -> list:
        """Reconstruct Block objects from the SQLite database."""
        from blockchain import Block   # local import avoids circular ref risk
        chain_data = self.storage.load_chain()
        return [Block.from_dict(bd) for bd in chain_data]

    def _save_meta_to_storage(self) -> None:
        """Persist current difficulty and retarget config to node_meta."""
        if not self.storage:
            return
        self.storage.save_meta("difficulty",        self.difficulty)
        self.storage.save_meta("retarget_interval", self.retarget_interval)
        self.storage.save_meta("target_block_time", self.target_block_time)
        self.storage.save_meta("min_difficulty",    self.min_difficulty)
        self.storage.save_meta("max_difficulty",    self.max_difficulty)


    # ------------------------------------------------------------------
    # Genesis
    # ------------------------------------------------------------------

    def _create_genesis_block(self) -> Block:
        """Mine and return the first block (index 0, no previous hash)."""
        print("Creating genesis block...")
        genesis = Block(index=0, transactions=[], previous_hash="0",
                        difficulty=self.difficulty)
        genesis.mine()
        print(f"  Genesis hash : {genesis.hash}")
        print(f"  Genesis nonce: {genesis.nonce}")
        print()
        return genesis

    # ------------------------------------------------------------------
    # Chain accessors
    # ------------------------------------------------------------------

    def get_latest_block(self) -> Block:
        return self.chain[-1]

    @property
    def height(self) -> int:
        """Number of blocks in the chain (including genesis)."""
        return len(self.chain)

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def add_transaction(self, transaction: dict) -> int:
        """Validate and buffer a transaction until the next block is mined.

        Stage 2 enforcement  (ECDSA)
        ----------------------------
        Every transaction must carry a valid ECDSA signature produced by
        the private key that corresponds to the `sender` address.  If the
        signature is missing, forged, or belongs to a different key-pair
        the transaction is rejected with a ValueError.

        Stage 7 enforcement  (UTXO / double-spend)
        -------------------------------------------
        After the signature is verified, the transaction is checked against
        the confirmed chain balance AND the current mempool:

          1. Coinbase forgery  -- only NETWORK may set sender='NETWORK'
          2. Positive amount   -- amount > 0
          3. Self-send         -- sender != recipient
          4. Available balance -- confirmed - pending_outgoing >= amount
          5. Duplicate mempool -- identical tx (same sig) already pending

        Coinbase / network-reward transactions (sender == 'NETWORK') are
        generated internally and bypass signature checking but still hit
        the UTXOState coinbase-forgery rule for externally submitted txns.

        Parameters
        ----------
        transaction : dict
            Keys required for user txns:
              sender, recipient, amount, public_key, signature

        Returns
        -------
        int  -- index of the block that will confirm this transaction.

        Raises
        ------
        ValueError  -- if the ECDSA signature is invalid, balance is
                       insufficient, or any other pre-flight check fails.
        """
        # ── Stage 2: ECDSA signature check ────────────────────────
        if not Wallet.verify_transaction(transaction):
            sender = transaction.get("sender", "<unknown>")
            raise ValueError(
                f"[Blockchain] Rejected transaction from {sender}: "
                "invalid or missing ECDSA signature."
            )

        # ── Stage 7: UTXO balance + double-spend check ─────────────
        if UTXOState is not None:
            snapshot = UTXOState(self.chain, storage=self.storage)
            ok, reason = snapshot.validate_transaction(
                transaction, self.pending_transactions
            )
            if not ok:
                raise ValueError(f"[Blockchain] Transaction rejected: {reason}")

        self.pending_transactions.append(transaction)
        return self.height  # index of the block that will confirm it

    # ------------------------------------------------------------------
    # Mining
    # ------------------------------------------------------------------

    def mine_pending_transactions(self, miner_address: str) -> Block:
        """Bundle pending transactions + coinbase reward into a new block.

        Stage 9A — Fee prioritisation
        ------------------------------
        1. Filter out time-locked txns not yet mature (lock_until_block).
        2. Sort remaining mempool by `fee` descending (highest fee first).
        3. Take the top MAX_TXNS_PER_BLOCK user transactions.
        4. Coinbase = BLOCK_REWARD + sum(fees of selected txns).

        Time-locked txns remain in the mempool until their block arrives.

        Parameters
        ----------
        miner_address : The DRN address that receives the block reward + fees.

        Returns
        -------
        The newly mined and appended Block.
        """
        next_index = len(self.chain)   # this will be the new block's index

        # ── Stage 9C: filter time-locked transactions ─────────────────
        ready, locked = [], []
        for tx in self.pending_transactions:
            lock = tx.get("lock_until_block", 0)
            if lock and lock > next_index:
                locked.append(tx)      # stays in mempool
            else:
                ready.append(tx)       # eligible to be mined

        # ── Stage 9A: sort by fee desc, cap at MAX_TXNS_PER_BLOCK ─────
        ready_sorted = sorted(
            ready,
            key=lambda t: float(t.get("fee", 0)),
            reverse=True,
        )
        selected  = ready_sorted[:self.MAX_TXNS_PER_BLOCK]
        leftover  = ready_sorted[self.MAX_TXNS_PER_BLOCK:]  # bumped to next block

        # ── Fees → coinbase ───────────────────────────────────────────
        total_fees  = sum(float(tx.get("fee", 0)) for tx in selected)
        coinbase_tx = {
            "sender":    "NETWORK",
            "recipient": miner_address,
            "amount":    self.BLOCK_REWARD + total_fees,
        }

        transactions = selected + [coinbase_tx]

        block = Block(
            index=next_index,
            transactions=transactions,
            previous_hash=self.get_latest_block().hash,
            difficulty=self.difficulty,
        )

        locked_count   = len(locked)
        leftover_count = len(leftover)
        print(f"  Mining block {block.index}...  "
              f"({len(selected)} txns, {locked_count} locked, "
              f"{leftover_count} bumped, fees={total_fees:.4f} DRN)")
        start = time.perf_counter()
        block.mine()
        elapsed = time.perf_counter() - start

        print(f"  [OK] Block {block.index} mined in {elapsed:.2f}s")
        print(f"    Hash  : {block.hash}")
        print(f"    Nonce : {block.nonce:,}")
        print(f"    Txns  : {len(transactions)}  (reward={self.BLOCK_REWARD}+{total_fees:.4f} fees)")

        self.chain.append(block)
        # Preserve locked + bumped txns for the next block
        self.pending_transactions = locked + leftover

        # Stage 4: attempt difficulty retarget
        retarget = self._adjust_difficulty()
        if retarget:
            tag = "CHANGED" if retarget["changed"] else "no change"
            print(f"  [Retarget @{retarget['block_height']}] "
                  f"{retarget['old_difficulty']} -> {retarget['new_difficulty']} "
                  f"({tag})")
            print(f"    actual={retarget['actual_time']:.2f}s  "
                  f"target={retarget['target_time']:.2f}s  "
                  f"ratio={retarget['ratio']:.3f}x")

        # Stage 5: persist the new block (and updated difficulty) to SQLite
        if self.storage:
            self.storage.save_block(block)
            self._save_meta_to_storage()

        return block

    # ------------------------------------------------------------------
    # Stage 4 -- Difficulty Retargeting
    # ------------------------------------------------------------------

    def _adjust_difficulty(self) -> dict:
        """Retarget PoW difficulty every `retarget_interval` blocks.

        Algorithm (simplified Bitcoin):
          1. Measure actual wall-clock time for the last N blocks.
          2. Compare to N * target_block_time.
          3. Scale: ratio = target_time / actual_time
               ratio > 1  -> blocks too fast  -> difficulty UP
               ratio < 1  -> blocks too slow  -> difficulty DOWN
          4. Clamp ratio to [0.25, 4.0] (Bitcoin's same 4x guard).
          5. Round to integer; clamp to [min_difficulty, max_difficulty].
          6. Always appends to self.retarget_log.

        Returns the event dict, or {} if not at an interval boundary.
        """
        height = len(self.chain)

        # Fire only at interval boundaries; skip genesis window
        if height < self.retarget_interval or height % self.retarget_interval != 0:
            return {}

        start_block = self.chain[-self.retarget_interval]
        end_block   = self.chain[-1]

        actual_time = end_block.timestamp - start_block.timestamp
        target_time = self.retarget_interval * self.target_block_time

        # Guard against clock skew / sub-millisecond unit-test runs
        if actual_time <= 0:
            actual_time = 1e-6

        # Scale ratio then clamp (prevents 100x swings)
        raw_ratio = target_time / actual_time
        ratio     = max(0.25, min(4.0, raw_ratio))

        old_difficulty = self.difficulty
        new_difficulty = max(
            self.min_difficulty,
            min(self.max_difficulty, round(old_difficulty * ratio)),
        )
        self.difficulty = new_difficulty

        event = {
            "block_height":   height,
            "actual_time":    round(actual_time, 4),
            "target_time":    round(target_time, 4),
            "raw_ratio":      round(raw_ratio,   4),
            "ratio":          round(ratio,        4),
            "old_difficulty": old_difficulty,
            "new_difficulty": new_difficulty,
            "changed":        new_difficulty != old_difficulty,
        }
        self.retarget_log.append(event)
        return event

    def retarget_status(self) -> dict:
        """Return a snapshot of the current retarget window (for API use)."""
        height = len(self.chain)
        mod    = height % self.retarget_interval

        blocks_until    = (self.retarget_interval - mod) if mod else self.retarget_interval
        window_len      = mod or self.retarget_interval
        window_start    = self.chain[-window_len]
        window_elapsed  = self.chain[-1].timestamp - window_start.timestamp
        avg_block_time  = window_elapsed / window_len if window_len > 1 else 0.0

        return {
            "current_difficulty":    self.difficulty,
            "retarget_interval":     self.retarget_interval,
            "target_block_time_s":   self.target_block_time,
            "min_difficulty":        self.min_difficulty,
            "max_difficulty":        self.max_difficulty,
            "chain_height":          height,
            "blocks_until_retarget": blocks_until,
            "next_retarget_at":      height + blocks_until,
            "avg_block_time_s":      round(avg_block_time, 3),
            "retarget_count":        len(self.retarget_log),
            "retarget_log":          self.retarget_log,
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        """Verify the integrity of every block in the chain.

        Checks (per block, starting at index 1):
          1. The stored hash matches a fresh recalculation.
          2. The previous_hash pointer links correctly to the prior block.
          3. The hash satisfies the declared difficulty (starts with
             the right number of leading zeros).

        The genesis block (index 0) is implicitly trusted.
        """
        for i in range(1, len(self.chain)):
            current  = self.chain[i]
            previous = self.chain[i - 1]

            # 1 — hash integrity
            if current.hash != current.calculate_hash():
                print(f"  [!!] Block {i}: hash mismatch (tampered data?)")
                return False

            # 2 — chain linkage
            if current.previous_hash != previous.hash:
                print(f"  [!!] Block {i}: broken chain link")
                return False

            # 3 — proof-of-work
            if not current.hash.startswith("0" * current.difficulty):
                print(f"  [!!] Block {i}: fails proof-of-work check")
                return False

        return True

    # ------------------------------------------------------------------
    # Peer / network chain helpers  (Stage 3)
    # ------------------------------------------------------------------

    @staticmethod
    def valid_chain_data(chain_data: list) -> bool:
        """Validate a chain represented as a list of plain dicts (JSON).

        This is the peer-chain variant of is_valid():  it works on raw
        dicts received from a network response rather than on local Block
        objects, so we can check a foreign chain without fully importing it.

        Checks per block (skipping genesis):
          1. Stored hash matches a fresh recalculation.
          2. previous_hash links correctly to the preceding block's hash.
          3. Hash satisfies the declared difficulty (leading zeros).
        """
        if not chain_data:
            return False

        for i in range(1, len(chain_data)):
            current_data  = chain_data[i]
            previous_data = chain_data[i - 1]

            # Reconstruct a transient Block object to recompute its hash
            current = Block.from_dict(current_data)

            # 1 — hash integrity
            if current.hash != current.calculate_hash():
                return False

            # 2 — chain linkage
            if current.previous_hash != previous_data["hash"]:
                return False

            # 3 — proof-of-work
            if not current.hash.startswith("0" * current.difficulty):
                return False

        return True

    def load_chain_from_data(self, chain_data: list) -> None:
        """Replace the local chain with Block objects reconstructed from
        a peer's JSON chain data.

        Called by the /nodes/resolve endpoint when a longer valid chain
        is found among peers.  Pending transactions are intentionally
        preserved -- they haven't been confirmed yet.

        Stage 5: also persists the replaced chain to SQLite so the node
        survives a restart with the correct (consensus) chain.
        """
        self.chain = [Block.from_dict(b) for b in chain_data]

        # Persist the replaced chain so the node survives a restart
        if self.storage:
            self.storage.save_chain(self.chain)
            self._save_meta_to_storage()

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def get_balance(self, address: str) -> float:
        """Return the net DRN balance for `address`.

        Stage 5 fast path: if a storage backend is attached, delegates
        to a SQL SUM query which is O(log n) via index instead of O(n).
        Falls back to a full chain scan when no storage is configured.
        """
        if self.storage:
            return self.storage.get_balance(address)

        # Fallback: walk every transaction in every block
        balance = 0.0
        for block in self.chain:
            for tx in block.transactions:
                if tx["recipient"] == address:
                    balance += tx["amount"]
                if tx["sender"] == address:
                    balance -= tx["amount"]
        return balance

    def get_utxo_snapshot(self) -> dict:
        """Return confirmed balances and mempool-aware available balances.

        Used by GET /utxo.  Shows every address that has ever received DRN,
        their confirmed on-chain balance, their pending outgoing amount, and
        their spendable (available) balance.

        Stage 7: delegates to UTXOState for consistent logic.
        """
        if UTXOState is None:
            return {"error": "UTXOState module not available"}

        snapshot = UTXOState(self.chain, storage=self.storage)
        confirmed = snapshot.all_confirmed_balances()

        result = {}
        for addr, bal in confirmed.items():
            pending_out = snapshot.pending_outgoing(addr, self.pending_transactions)
            result[addr] = {
                "confirmed":    round(bal, 8),
                "pending_out":  round(pending_out, 8),
                "available":    round(bal - pending_out, 8),
            }
        return result

    # ------------------------------------------------------------------
    # Pretty-print
    # ------------------------------------------------------------------

    def print_chain(self) -> None:
        """Dump a human-readable summary of every block."""
        print("=" * 60)
        print(f"  DorianCoin Blockchain  (height={self.height})")
        print("=" * 60)
        for block in self.chain:
            label = "GENESIS" if block.index == 0 else f"Block {block.index}"
            print(f"\n  [{label}]")
            print(f"    Hash     : {block.hash}")
            print(f"    PrevHash : {block.previous_hash}")
            print(f"    Nonce    : {block.nonce:,}")
            print(f"    Txns     : {len(block.transactions)}")
        print()
