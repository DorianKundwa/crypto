"""
utxo.py -- DorianCoin (DRN) UTXO Balance State  (Stage 7)
==========================================================
Computes and validates account balances from the confirmed chain
and detects double-spends in the pending transaction mempool.

While DorianCoin uses a simplified account model (sender/recipient/amount)
rather than Bitcoin's full UTXO input/output model, this module provides
all the protection that UTXO tracking exists for:

  1.  Insufficient-funds rejection  -- you can't spend coins you don't have
  2.  Mempool-aware balance check   -- pending outgoing txns are deducted
  3.  Duplicate / replay rejection  -- identical tx already in mempool
  4.  Self-send rejection           -- sender == recipient blocked
  5.  Coinbase-forgery rejection    -- only NETWORK may issue coinbase txns

Design
------
  UTXOState is a lightweight snapshot object.  It is rebuilt from the
  confirmed chain on every call to Blockchain.add_transaction(), which is
  the only place where external txns enter the system.  Because mining is
  infrequent (seconds to minutes), the O(n) chain scan is negligible.

  For large chains the storage.get_balance() SQL path (O(log n)) can
  replace the scan, and the class wires to it automatically.

Usage
-----
    from utxo import UTXOState

    snapshot = UTXOState(blockchain.chain)
    ok, err = snapshot.validate_transaction(tx, blockchain.pending_transactions)
    if not ok:
        raise ValueError(err)
"""

from __future__ import annotations
from typing import Optional


class UTXOState:
    """Confirmed balance snapshot + mempool-aware spend validation.

    Parameters
    ----------
    chain   : list of Block objects (the confirmed chain)
    storage : Optional BlockchainStorage  -- if supplied, balance queries
              are answered via fast SQL rather than a full chain scan.
    """

    def __init__(self, chain: list, storage=None):
        self._storage = storage
        if storage:
            # SQL path: delegate confirmed balance lookups to the DB
            self._balances: dict[str, float] = {}   # only populated on demand
            self._sql_mode = True
        else:
            self._balances = self._build(chain)
            self._sql_mode = False

    # ------------------------------------------------------------------
    # Internal build
    # ------------------------------------------------------------------

    @staticmethod
    def _build(chain: list) -> dict[str, float]:
        """Walk every confirmed block and sum up debits/credits per address."""
        balances: dict[str, float] = {}
        for block in chain:
            for tx in block.transactions:
                recipient = tx.get("recipient", "")
                sender    = tx.get("sender", "")
                amount    = float(tx.get("amount", 0))
                balances[recipient] = balances.get(recipient, 0.0) + amount
                if sender and sender != "NETWORK":
                    balances[sender] = balances.get(sender, 0.0) - amount
        return balances

    # ------------------------------------------------------------------
    # Balance queries
    # ------------------------------------------------------------------

    def confirmed_balance(self, address: str) -> float:
        """Return the confirmed (on-chain) balance for `address`."""
        if self._sql_mode:
            return self._storage.get_balance(address)
        return max(0.0, self._balances.get(address, 0.0))

    def pending_outgoing(self, address: str, pending_txns: list) -> float:
        """Sum of all outgoing amounts for `address` currently in the mempool."""
        return sum(
            float(tx.get("amount", 0))
            for tx in pending_txns
            if tx.get("sender") == address
        )

    def available_balance(self, address: str, pending_txns: list) -> float:
        """Spendable balance = confirmed − pending outgoing.

        This is the correct amount to check against when accepting a new
        transaction -- it prevents the classic scenario where Alice has
        50 DRN confirmed, submits a 50 DRN tx to Bob, then immediately
        submits another 50 DRN tx to Carol before the first is mined.
        """
        return self.confirmed_balance(address) - self.pending_outgoing(address, pending_txns)

    def all_confirmed_balances(self) -> dict[str, float]:
        """Return every address with a positive confirmed balance."""
        if self._sql_mode:
            # Reconstruct from DB for all addresses with transactions
            rows = self._storage._conn().execute(
                """SELECT DISTINCT recipient FROM transactions
                   UNION
                   SELECT DISTINCT sender FROM transactions WHERE sender != 'NETWORK'"""
            ).fetchall()
            result = {}
            for (addr,) in rows:
                bal = self._storage.get_balance(addr)
                if bal > 0:
                    result[addr] = round(bal, 8)
            return result
        return {a: round(b, 8) for a, b in self._balances.items() if b > 0}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_transaction(
        self,
        tx: dict,
        pending_txns: list,
    ) -> tuple[bool, Optional[str]]:
        """Full transaction pre-flight check.

        Checks (in order):
        ------------------
        1. Coinbase forgery  -- only NETWORK may set sender='NETWORK'
        2. Positive amount   -- amount > 0
        3. Self-send         -- sender != recipient
        4. Available balance -- confirmed_balance - pending_outgoing >= amount
        5. Duplicate mempool -- exact (sender, recipient, amount) match

        Returns
        -------
        (True, None)        -- tx is valid, safe to add to mempool
        (False, reason_str) -- tx is rejected; reason explains why
        """
        sender    = tx.get("sender",    "")
        recipient = tx.get("recipient", "")
        amount    = float(tx.get("amount", 0))

        # ── 1. Coinbase forgery ────────────────────────────────────
        if sender == "NETWORK":
            return False, (
                "Coinbase forgery: only the network may set sender='NETWORK'. "
                "Craft a normal signed transaction instead."
            )

        # ── 2. Positive amount ─────────────────────────────────────
        if amount <= 0:
            return False, f"Amount must be positive (got {amount})."

        # ── 3. Self-send ───────────────────────────────────────────
        if sender == recipient:
            return False, "Sender and recipient must be different addresses."

        # ── 4. Duplicate in mempool (check before balance) ─────────
        # Replaying the same signed transaction is caught here first,
        # giving a clearer "duplicate" message rather than "overdraft".
        for p in pending_txns:
            if (
                p.get("sender")    == sender
                and p.get("recipient") == recipient
                and float(p.get("amount", 0)) == amount
                and p.get("signature") == tx.get("signature")
            ):
                return False, (
                    "Duplicate transaction: an identical tx from the same sender "
                    "is already in the mempool."
                )

        # ── 5. Available balance ───────────────────────────────────
        confirmed   = self.confirmed_balance(sender)
        pending_out = self.pending_outgoing(sender, pending_txns)
        available   = confirmed - pending_out

        if amount > available:
            if confirmed <= 0:
                reason = (
                    f"Address {sender[:20]}… has no confirmed balance. "
                    f"You need at least {amount} DRN."
                )
            elif pending_out > 0:
                reason = (
                    f"Double-spend detected: requested {amount:.4f} DRN but only "
                    f"{available:.4f} DRN is available "
                    f"(confirmed={confirmed:.4f}, pending_out={pending_out:.4f})."
                )
            else:
                reason = (
                    f"Insufficient funds: requested {amount:.4f} DRN, "
                    f"confirmed balance is {confirmed:.4f} DRN."
                )
            return False, reason

        return True, None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Return a serialisable summary of the current balance state."""
        return {
            "mode":      "sql" if self._sql_mode else "chain_scan",
            "balances":  self.all_confirmed_balances(),
        }
