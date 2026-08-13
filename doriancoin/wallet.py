"""
wallet.py — DorianCoin (DRN) Cryptographic Wallet
==================================================
Stage 2: ECDSA key pairs on secp256k1 (same curve as Bitcoin),
         Base58Check address derivation, transaction signing,
         and static signature verification.

Key pipeline:
  Private Key (secp256k1)
       |
  Public Key  (uncompressed X9.62, 65 bytes)
       |
  SHA-256(pub_bytes)[:20]        ← simplified hash160
       |
  version_byte + 20-byte hash    ← payload
       |
  Base58Check encode             ← checksum included
       |
  "DRN" prefix                   ← human-readable marker
       =
  DRN address  (e.g. DRN1A8Xxz...)

Later stages will add:
  - HD wallets / BIP-32 derivation paths
  - Wallet persistence with AES-encrypted key files
  - Multi-sig support
"""

import hashlib
import json
import os
from typing import Optional

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature


# ---------------------------------------------------------------------------
# Base58 / Base58Check  (no external library needed)
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    """Encode raw bytes to a Base58 string (no checksum)."""
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    num = int.from_bytes(data, "big")
    result = []
    while num:
        num, remainder = divmod(num, 58)
        result.append(_B58_ALPHABET[remainder])
    return "1" * leading_zeros + "".join(reversed(result))


def _b58check_encode(payload: bytes) -> str:
    """Encode bytes to Base58Check  (payload + first-4-bytes of SHA256d)."""
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _b58encode(payload + checksum)


def _b58check_decode(text: str) -> bytes:
    """Decode a Base58Check string and return the payload (without checksum).

    Raises ValueError if the checksum does not match.
    """
    # Decode base58 → integer
    num = 0
    leading = 0
    for char in text:
        if char not in _B58_ALPHABET:
            raise ValueError(f"Invalid Base58 character: {char!r}")
        num = num * 58 + _B58_ALPHABET.index(char)
    for char in text:
        if char == "1":
            leading += 1
        else:
            break

    # Convert integer → bytes
    data = b"\x00" * leading + num.to_bytes((num.bit_length() + 7) // 8, "big")

    payload, chk = data[:-4], data[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if chk != expected:
        raise ValueError("Base58Check checksum mismatch — address may be corrupt.")
    return payload


# ---------------------------------------------------------------------------
# Address derivation helpers
# ---------------------------------------------------------------------------

_VERSION_BYTE = b"\x00"    # mainnet version byte (like Bitcoin P2PKH)
_DRN_PREFIX   = "DRN"      # human-readable brand prefix


def pubkey_to_address(public_key: ec.EllipticCurvePublicKey) -> str:
    """Derive a DRN address from an ECDSA public key.

    Steps:
      1. Serialize to uncompressed X9.62 (04 || x || y)  — 65 bytes
      2. SHA-256 of those bytes
      3. Take the first 20 bytes  (replaces RIPEMD-160 for simplicity)
      4. Prepend the version byte (0x00)
      5. Base58Check encode
      6. Prepend the 'DRN' human-readable prefix
    """
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    sha_digest = hashlib.sha256(pub_bytes).digest()
    key_hash   = sha_digest[:20]                    # 20-byte hash
    payload    = _VERSION_BYTE + key_hash
    return _DRN_PREFIX + _b58check_encode(payload)


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------

class Wallet:
    """A DorianCoin ECDSA wallet.

    Attributes
    ----------
    private_key : ec.EllipticCurvePrivateKey
        The secp256k1 private key.  Keep this secret — it controls your funds.
    public_key  : ec.EllipticCurvePublicKey
        The corresponding public key — safe to share.
    address     : str
        The derived DRN address (e.g. 'DRN1A8Xxz...') — your identity on chain.
    """

    CURVE = ec.SECP256K1()    # same elliptic curve as Bitcoin / Ethereum

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, private_key: Optional[ec.EllipticCurvePrivateKey] = None):
        """Create a wallet.  Pass `private_key=None` to generate a fresh one."""
        if private_key is None:
            self.private_key = ec.generate_private_key(
                self.CURVE, default_backend()
            )
        else:
            self.private_key = private_key

        self.public_key: ec.EllipticCurvePublicKey = self.private_key.public_key()
        self.address: str = pubkey_to_address(self.public_key)

    # ------------------------------------------------------------------
    # Key serialisation
    # ------------------------------------------------------------------

    def get_public_key_hex(self) -> str:
        """Return the uncompressed public key as a lowercase hex string.

        This is included in every signed transaction so that any node can
        verify the signature without contacting a PKI or key server.
        """
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        ).hex()

    def export_private_key_pem(self,
                               password: Optional[bytes] = None) -> bytes:
        """Serialize the private key to PKCS8 PEM format.

        Pass a `password` to encrypt the PEM with AES-256-CBC — strongly
        recommended for any key stored to disk.
        """
        encryption = (
            serialization.BestAvailableEncryption(password)
            if password
            else serialization.NoEncryption()
        )
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, filepath: str,
             password: Optional[bytes] = None) -> None:
        """Write the private key PEM to `filepath`.

        If the parent directory does not exist it is created automatically.
        """
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "wb") as fh:
            fh.write(self.export_private_key_pem(password))
        print(f"[Wallet] Private key saved -> {filepath}")

    @classmethod
    def load(cls, filepath: str,
             password: Optional[bytes] = None) -> "Wallet":
        """Load a wallet from a PEM file and return a new Wallet instance."""
        with open(filepath, "rb") as fh:
            pem_data = fh.read()
        private_key = serialization.load_pem_private_key(
            pem_data, password=password, backend=default_backend()
        )
        wallet = cls(private_key=private_key)
        print(f"[Wallet] Loaded from {filepath}  ->  {wallet.address}")
        return wallet

    # ------------------------------------------------------------------
    # Transaction creation & signing
    # ------------------------------------------------------------------

    def create_transaction(self, recipient: str, amount: float) -> dict:
        """Build, sign, and return a transaction dict.

        The returned dict contains everything a node needs to:
          • Display the transfer   (sender, recipient, amount)
          • Verify authenticity    (public_key, signature)

        Dict schema::

            {
                "sender"    : "DRN1...",
                "recipient" : "DRN1...",
                "amount"    : 10.0,
                "public_key": "04ab...",   # 130-hex uncompressed pub key
                "signature" : "3045..."    # DER-encoded ECDSA sig, hex
            }
        """
        if amount <= 0:
            raise ValueError(f"Transaction amount must be positive, got {amount}")

        tx_body = {
            "sender":    self.address,
            "recipient": recipient,
            "amount":    amount,
        }
        signature = self._sign(tx_body)

        return {
            **tx_body,
            "public_key": self.get_public_key_hex(),
            "signature":  signature,
        }

    def _sign(self, data: dict) -> str:
        """ECDSA-sign a canonical-JSON encoding of `data`.

        Steps:
          1. json.dumps with sort_keys=True → deterministic bytes
          2. private_key.sign(...)  → DER-encoded signature bytes
          3. Return as lowercase hex string
        """
        encoded  = json.dumps(data, sort_keys=True).encode()
        der_sig  = self.private_key.sign(encoded, ec.ECDSA(hashes.SHA256()))
        return der_sig.hex()

    # ------------------------------------------------------------------
    # Static verification  (used by Blockchain.add_transaction)
    # ------------------------------------------------------------------

    @staticmethod
    def verify_transaction(tx: dict) -> bool:
        """Verify the ECDSA signature embedded in a transaction dict.

        Returns True  if the signature is cryptographically valid.
        Returns False if anything is missing, malformed, or tampered.

        Coinbase / network reward transactions (sender == 'NETWORK') are
        implicitly trusted and always return True.
        """
        if tx.get("sender") == "NETWORK":
            return True          # minted coins — no signature expected

        required = {"sender", "recipient", "amount", "public_key", "signature"}
        if not required.issubset(tx):
            return False

        try:
            # Reconstruct public key from the hex bytes in the transaction
            pub_bytes  = bytes.fromhex(tx["public_key"])
            public_key = ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256K1(), pub_bytes
            )

            # Re-derive the address from the public key and check it matches
            derived_address = pubkey_to_address(public_key)
            if derived_address != tx["sender"]:
                return False     # public_key doesn't match the claimed sender

            # Reconstruct the exact bytes that were signed
            tx_body  = {
                "sender":    tx["sender"],
                "recipient": tx["recipient"],
                "amount":    tx["amount"],
            }
            encoded  = json.dumps(tx_body, sort_keys=True).encode()
            der_sig  = bytes.fromhex(tx["signature"])

            public_key.verify(der_sig, encoded, ec.ECDSA(hashes.SHA256()))
            return True

        except (InvalidSignature, KeyError, ValueError, Exception):
            return False

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Wallet(address={self.address!r})"
