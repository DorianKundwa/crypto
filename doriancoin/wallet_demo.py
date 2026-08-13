"""
wallet_demo.py — DorianCoin Stage 2: Wallets + Signed Transactions
===================================================================
Demonstrates:
  1.  Generating real ECDSA wallets with DRN addresses
  2.  Creating and signing transactions
  3.  Blockchain rejecting forged / unsigned transactions
  4.  Balance accounting across multiple signed transfers
  5.  Saving and reloading a wallet from disk

Run:
    python wallet_demo.py
"""

import os
from wallet import Wallet
from blockchain import Blockchain

DIVIDER = "=" * 60


def section(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def balances(chain: Blockchain, **wallets) -> None:
    """Print balances for a dict of name→wallet pairs."""
    for name, w in wallets.items():
        bal = chain.get_balance(w.address)
        print(f"  {name:<8} {w.address}  =>  {bal} DRN")


# ---------------------------------------------------------------------------
# 1. Generate wallets
# ---------------------------------------------------------------------------
section("1. Generating Wallets")

alice = Wallet()
bob   = Wallet()
miner = Wallet()

print(f"  Alice : {alice.address}")
print(f"  Bob   : {bob.address}")
print(f"  Miner : {miner.address}")

# Quick sanity check — two wallets must never produce the same address
assert alice.address != bob.address != miner.address, "Address collision!"
print("\n  [OK] All three addresses are unique.")


# ---------------------------------------------------------------------------
# 2. Inspect a transaction dict before it hits the chain
# ---------------------------------------------------------------------------
section("2. Inspecting a Signed Transaction")

sample_tx = miner.create_transaction(alice.address, 20)
print("  Keys in a signed transaction:")
for k, v in sample_tx.items():
    display = v if k != "public_key" else v[:24] + "..."
    display = display if k != "signature"  else display[:24] + "..."
    print(f"    {k:<12}: {display}")

verified = Wallet.verify_transaction(sample_tx)
print(f"\n  Signature valid? {verified}")
assert verified, "Signature verification failed!"


# ---------------------------------------------------------------------------
# 3. Start the blockchain and mine the first block
# ---------------------------------------------------------------------------
section("3. Starting Blockchain  (difficulty=4)")

chain = Blockchain(difficulty=4)

print("\n  Mining block 1  (miner earns block reward)...")
chain.mine_pending_transactions(miner.address)
print()
balances(chain, Alice=alice, Bob=bob, Miner=miner)


# ---------------------------------------------------------------------------
# 4. Miner → Alice: 20 DRN (signed)
# ---------------------------------------------------------------------------
section("4. Miner sends Alice 20 DRN  (signed transaction)")

tx1 = miner.create_transaction(alice.address, 20)
block_idx = chain.add_transaction(tx1)
print(f"\n  Transaction accepted. Will confirm in block {block_idx}.")
print("  Mining block 2...")
chain.mine_pending_transactions(miner.address)
print()
balances(chain, Alice=alice, Bob=bob, Miner=miner)


# ---------------------------------------------------------------------------
# 5. Alice → Bob: 8 DRN (signed)
# ---------------------------------------------------------------------------
section("5. Alice sends Bob 8 DRN  (signed transaction)")

tx2 = alice.create_transaction(bob.address, 8)
chain.add_transaction(tx2)
print("\n  Mining block 3...")
chain.mine_pending_transactions(miner.address)
print()
balances(chain, Alice=alice, Bob=bob, Miner=miner)


# ---------------------------------------------------------------------------
# 6. Bob → Alice: 3 DRN (signed)
# ---------------------------------------------------------------------------
section("6. Bob sends Alice 3 DRN  (signed transaction)")

tx3 = bob.create_transaction(alice.address, 3)
chain.add_transaction(tx3)
print("\n  Mining block 4...")
chain.mine_pending_transactions(miner.address)
print()
balances(chain, Alice=alice, Bob=bob, Miner=miner)


# ---------------------------------------------------------------------------
# 7. Chain integrity
# ---------------------------------------------------------------------------
section("7. Chain Integrity Check")

valid = chain.is_valid()
print(f"\n  Blockchain valid: {valid}")
assert valid, "Chain should be valid!"
chain.print_chain()


# ---------------------------------------------------------------------------
# 8. Forgery attempt — garbage signature
# ---------------------------------------------------------------------------
section("8. Attack: Forged Signature (garbage bytes)")

print("\n  Attempting to submit a transaction with a fake signature...")
fake_tx = {
    "sender":     alice.address,
    "recipient":  bob.address,
    "amount":     9_999,
    "public_key": alice.get_public_key_hex(),
    "signature":  "deadbeefdeadbeef",   # complete garbage
}
try:
    chain.add_transaction(fake_tx)
    print("  ERROR: forged transaction was accepted!")
    raise SystemExit(1)
except ValueError as e:
    print(f"  [BLOCKED] {e}")


# ---------------------------------------------------------------------------
# 9. Forgery attempt — valid sig but wrong sender address
# ---------------------------------------------------------------------------
section("9. Attack: Valid Sig, Wrong Sender Address")

print("\n  Attempting to claim Bob's address while signing with Alice's key...")
# Alice signs a tx that pretends to come from Bob's address
wrong_address_tx = {
    "sender":     bob.address,           # lying about the sender
    "recipient":  alice.address,
    "amount":     500,
    "public_key": alice.get_public_key_hex(),  # but signing with Alice's key
    "signature":  alice._sign({
        "sender":    bob.address,
        "recipient": alice.address,
        "amount":    500,
    }),
}
try:
    chain.add_transaction(wrong_address_tx)
    print("  ERROR: spoofed-sender transaction was accepted!")
    raise SystemExit(1)
except ValueError as e:
    print(f"  [BLOCKED] {e}")


# ---------------------------------------------------------------------------
# 10. Save and reload a wallet
# ---------------------------------------------------------------------------
section("10. Wallet Persistence")

wallet_path = os.path.join("data", "alice_wallet.pem")
alice.save(wallet_path)

alice_reloaded = Wallet.load(wallet_path)
assert alice_reloaded.address == alice.address, "Reloaded address mismatch!"
print(f"  Reloaded address matches original: {alice_reloaded.address}")

# Make sure reloaded wallet can still sign valid transactions
tx_reload = alice_reloaded.create_transaction(bob.address, 1)
assert Wallet.verify_transaction(tx_reload), "Reloaded wallet signing failed!"
print("  [OK] Reloaded wallet can sign valid transactions.")


# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
section("Stage 2 Complete!")

print("""
  What we built:
    - secp256k1 ECDSA key pairs (same curve as Bitcoin)
    - Deterministic DRN addresses via SHA-256 + Base58Check
    - Transaction signing  (private key signs canonical JSON body)
    - Signature verification  (public key + address cross-check)
    - Blockchain rejects ALL unsigned / forged / spoofed transactions
    - Wallet save / load  (PKCS8 PEM)

  What's next  (Stage 3 — Flask REST Node):
    - POST /transactions/new   =>  submit a signed tx
    - GET  /mine               =>  trigger PoW and earn DRN
    - GET  /chain              =>  inspect the full blockchain
    - Two nodes talking to each other over HTTP
""")
