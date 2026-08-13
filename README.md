# DorianCoin (DRN)

A Bitcoin-like cryptocurrency built from scratch in Python.

## Architecture

```
doriancoin/
├── blockchain.py      # Core: blocks, SHA-256 PoW, ECDSA verification, retargeting
├── wallet.py          # secp256k1 keys, Base58Check addresses, ECDSA signing
├── node.py            # Flask REST node — 12 endpoints, P2P consensus
├── miner.py           # Stage 1 demo
├── wallet_demo.py     # Stage 2 demo
├── p2p_demo.py        # Stage 3 demo — two-node P2P network
├── retarget_demo.py   # Stage 4 demo — difficulty retargeting
└── requirements.txt   # Python dependencies
```

## Stages

| Stage | Feature | Status |
|-------|---------|--------|
| 1 | Blockchain — blocks, SHA-256 PoW, chain validation | ✅ Done |
| 2 | Wallets — secp256k1, Base58Check addresses, ECDSA signing | ✅ Done |
| 3 | P2P REST Node — Flask API, Nakamoto consensus | ✅ Done |
| 4 | Difficulty Retargeting — auto-adjusts every N blocks | ✅ Done |
| 5 | Persistent Storage — SQLite backend | 🔜 Next |
| 6 | Block Explorer — web UI | 🔜 Planned |
| 7 | Mining Pools | 🔜 Planned |

## Quick Start

```bash
# Install dependencies
pip install -r doriancoin/requirements.txt

# Run Stage 1 demo (blockchain + PoW)
python doriancoin/miner.py

# Run Stage 2 demo (wallets + signatures)
python doriancoin/wallet_demo.py

# Run Stage 3 demo (two-node P2P network)
python doriancoin/p2p_demo.py

# Run Stage 4 demo (difficulty retargeting)
python doriancoin/retarget_demo.py

# Start a node manually
python doriancoin/node.py --port 5000 --difficulty 3 \
       --retarget-interval 10 --target-block-time 5
```

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Node info + retarget status |
| GET | `/chain` | Full blockchain as JSON |
| GET | `/mine` | Mine a new block (PoW) |
| GET | `/difficulty` | Retarget history + current difficulty |
| GET | `/balance/<addr>` | Confirmed DRN balance |
| POST | `/transactions/new` | Submit signed transaction |
| POST | `/nodes/register` | Register a peer node |
| GET | `/nodes/resolve` | Nakamoto consensus sync |

## How Difficulty Retargeting Works

Every `N` blocks, the algorithm measures how long those blocks actually took:

```
ratio         = target_time / actual_time   (clamped to [0.25x, 4x])
new_difficulty = round(old_difficulty * ratio)
```

- **ratio > 1** → blocks came too fast → difficulty **increases**
- **ratio < 1** → blocks came too slow → difficulty **decreases**

## Dependencies

- `flask==2.3.3` + `werkzeug==2.3.7` — REST node
- `cryptography` — secp256k1 ECDSA signing
- `requests` — P2P peer communication

## License

MIT
