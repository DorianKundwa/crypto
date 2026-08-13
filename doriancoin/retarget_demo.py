"""
retarget_demo.py -- DorianCoin Stage 4: Difficulty Retargeting Demo
====================================================================
Demonstrates the automatic difficulty adjustment algorithm across
three distinct scenarios:

  A. Blocks too FAST  -> difficulty increases
  B. Blocks too SLOW  -> difficulty decreases
  C. Convergence      -> multiple retargets homing in on target

Run:
    python retarget_demo.py
"""

import time
import math
from blockchain import Blockchain

DIVIDER = "=" * 62
SUBDIV  = "-" * 62


def banner(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def sub(title: str) -> None:
    print(f"\n{SUBDIV}")
    print(f"  {title}")
    print(SUBDIV)


def mine_n(bc: Blockchain, n: int, label: str = "") -> list:
    """Mine n blocks silently, returning a list of (index, elapsed, nonce) tuples."""
    results = []
    for i in range(n):
        t0    = time.perf_counter()
        block = bc.mine_pending_transactions("DEMO_MINER")
        elapsed = time.perf_counter() - t0
        results.append((block.index, elapsed, block.nonce))
        stars = "*" if bc.retarget_log and bc.retarget_log[-1]["block_height"] == bc.height else " "
        print(f"  {stars} Block {block.index:>3}  diff={bc.difficulty}  "
              f"nonce={block.nonce:>8,}  {elapsed:.4f}s"
              + (f"  [RETARGET -> diff {bc.retarget_log[-1]['new_difficulty']}]"
                 if bc.retarget_log and bc.retarget_log[-1]["block_height"] == bc.height
                    and bc.retarget_log[-1]["changed"]
                 else ""))
    return results


def print_retarget_event(ev: dict) -> None:
    direction = "UP  ^" if ev["new_difficulty"] > ev["old_difficulty"] else \
                "DOWN v" if ev["new_difficulty"] < ev["old_difficulty"] else \
                "unchanged ="
    print(f"\n  >> RETARGET at block {ev['block_height']} <<")
    print(f"     Actual time   : {ev['actual_time']:.3f}s "
          f"(for {ev['block_height']} blocks in window)")
    print(f"     Target time   : {ev['target_time']:.3f}s")
    raw = ev['raw_ratio']
    print(f"     Raw ratio     : {raw:.3f}x  (clamped to {ev['ratio']:.3f}x)")
    print(f"     Difficulty    : {ev['old_difficulty']} -> {ev['new_difficulty']}  [{direction}]")
    approx_hashes = 16 ** ev['new_difficulty']
    print(f"     Expected hash attempts : ~{approx_hashes:,}")


# ---------------------------------------------------------------------------
# Scenario A — Blocks too FAST (difficulty should increase)
# ---------------------------------------------------------------------------

def scenario_a():
    sub("Scenario A: Blocks Too FAST  (difficulty should go UP)")

    print("""
  Config:
    starting difficulty : 2     (~256 expected hashes per block)
    retarget interval   : 5 blocks
    target block time   : 5.0 s per block  (blocks should take 5s each)

  At difficulty=2 Python mines in ~0.001s  <<  5s target
  After 5 blocks: actual~0.005s, target=25s, ratio clamped to 4x
  Expected new difficulty: min(MAX, round(2 * 4)) = 5
    """)

    bc = Blockchain(
        difficulty        = 2,
        retarget_interval = 5,
        target_block_time = 5.0,
        min_difficulty    = 1,
        max_difficulty    = 6,
    )

    print(f"  Starting: difficulty={bc.difficulty}, "
          f"next retarget at block {bc.retarget_interval}")
    print()

    results = mine_n(bc, 5, "fast")

    ev = bc.retarget_log[-1] if bc.retarget_log else None
    if ev:
        print_retarget_event(ev)

    # Mine 2 more blocks at the new difficulty so we can see the difference
    print(f"\n  Mining 2 more blocks at new difficulty={bc.difficulty}...")
    mine_n(bc, 2)

    avg_before = sum(r[1] for r in results) / len(results)
    avg_after  = sum(r[1] for r in mine_n(bc, 3)) / 3
    print(f"\n  Avg block time before retarget : {avg_before:.4f}s")
    print(f"  Avg block time after retarget  : {avg_after:.4f}s")
    print(f"  Speed ratio                    : {avg_after / avg_before:.1f}x slower (as expected)")
    return bc


# ---------------------------------------------------------------------------
# Scenario B — Blocks too SLOW (difficulty should decrease)
# ---------------------------------------------------------------------------

def scenario_b():
    sub("Scenario B: Blocks Too SLOW  (difficulty should go DOWN)")

    print("""
  Config:
    starting difficulty : 4     (~65,536 expected hashes per block)
    retarget interval   : 5 blocks
    target block time   : 0.001 s per block  (sub-millisecond target!)

  At difficulty=4 Python mines in ~0.3-1s  >>  0.001s target
  After 5 blocks: actual~2s, target=0.005s, raw ratio~0.0025x -> clamped 0.25x
  Expected new difficulty: max(MIN, round(4 * 0.25)) = 1
    """)

    bc = Blockchain(
        difficulty        = 4,
        retarget_interval = 5,
        target_block_time = 0.001,
        min_difficulty    = 1,
        max_difficulty    = 6,
    )

    print(f"  Starting: difficulty={bc.difficulty}")
    print()

    results = mine_n(bc, 5, "slow")

    ev = bc.retarget_log[-1] if bc.retarget_log else None
    if ev:
        print_retarget_event(ev)

    print(f"\n  Mining 3 more blocks at new difficulty={bc.difficulty} (should be instant)...")
    after = mine_n(bc, 3)

    avg_before = sum(r[1] for r in results) / len(results)
    avg_after  = sum(r[1] for r in after) / len(after)
    print(f"\n  Avg block time before retarget : {avg_before:.4f}s")
    print(f"  Avg block time after retarget  : {avg_after:.6f}s")
    ratio = avg_before / avg_after if avg_after > 0 else float("inf")
    print(f"  Speed ratio                    : {ratio:.0f}x faster (as expected)")
    return bc


# ---------------------------------------------------------------------------
# Scenario C — Convergence: simulate many retargets homing in on target
# ---------------------------------------------------------------------------

def scenario_c():
    sub("Scenario C: Convergence Simulation  (virtual blocks)")

    print("""
  This scenario does NOT mine real blocks — instead we inject fake
  timestamps to simulate 50 retarget periods and watch difficulty
  converge toward the target rate.

  Config:
    starting difficulty : 3
    retarget interval   : 5 blocks
    target block time   : 1.0 s per block
    actual block time   : starts at 0.1s (10x too fast) -> converges
    """)

    # We'll build a chain by directly appending blocks with fake timestamps
    # to avoid waiting for real PoW.  This is a pure algorithm visualisation.
    import hashlib, json

    class FakeBlock:
        def __init__(self, index, ts, prev_hash, difficulty):
            self.index        = index
            self.timestamp    = ts
            self.transactions = []
            self.previous_hash = prev_hash
            self.nonce        = 0
            self.difficulty   = difficulty
            self.hash         = self._compute_hash()

        def _compute_hash(self):
            payload = json.dumps({
                "index": self.index, "timestamp": self.timestamp,
                "transactions": [], "previous_hash": self.previous_hash,
                "nonce": self.nonce,
            }, sort_keys=True)
            return hashlib.sha256(payload.encode()).hexdigest()

        def to_dict(self):
            return self.__dict__

    # Bootstrap the simulation
    TARGET_BLOCK_TIME   = 1.0
    RETARGET_INTERVAL   = 5
    MIN_DIFF, MAX_DIFF  = 1, 8

    difficulty = 3
    # Real block time is a function of difficulty: assume 16^d / hash_rate hashes
    # where hash_rate ~ 50_000 hashes/sec on a modern CPU
    HASH_RATE       = 50_000
    retarget_events = []

    ts           = time.time() - 1000     # start 1000s ago (virtual)
    prev_hash    = "0" * 64
    chain        = []
    history      = []    # (block_index, difficulty, simulated_actual_block_time)

    print(f"  {'Block':>6}  {'Diff':>5}  {'Sim block time':>16}  {'Event'}")
    print(f"  {'-'*6}  {'-'*5}  {'-'*16}  {'-'*30}")

    for i in range(55):
        # Simulate how long a block at this difficulty would take
        expected_hashes  = 16 ** difficulty
        sim_block_time   = expected_hashes / HASH_RATE
        ts              += sim_block_time

        fb = FakeBlock(i, ts, prev_hash, difficulty)
        chain.append(fb)
        prev_hash = fb.hash
        history.append((i, difficulty, sim_block_time))

        event_label = ""

        # Retarget?
        height = len(chain)
        if height >= RETARGET_INTERVAL and height % RETARGET_INTERVAL == 0:
            start_ts    = chain[-RETARGET_INTERVAL].timestamp
            actual_time = ts - start_ts
            target_time = RETARGET_INTERVAL * TARGET_BLOCK_TIME

            actual_time = max(actual_time, 1e-9)
            raw_ratio   = target_time / actual_time
            ratio       = max(0.25, min(4.0, raw_ratio))
            new_diff    = max(MIN_DIFF, min(MAX_DIFF, round(difficulty * ratio)))

            ev = {"block": height, "old": difficulty, "new": new_diff,
                  "actual": actual_time, "target": target_time, "ratio": ratio}
            retarget_events.append(ev)
            event_label = (f"RETARGET {difficulty}->{new_diff}  "
                           f"({actual_time:.2f}s actual, {target_time:.2f}s target, "
                           f"ratio={ratio:.2f}x)")
            difficulty = new_diff

        print(f"  {i:>6}  {history[-1][1]:>5}  {sim_block_time:>14.4f}s  {event_label}")

    # Summary
    print(f"\n  Retarget history ({len(retarget_events)} events):")
    for ev in retarget_events:
        arrow = "^" if ev["new"] > ev["old"] else ("v" if ev["new"] < ev["old"] else "=")
        print(f"    Block {ev['block']:>3}:  diff {ev['old']} -> {ev['new']} {arrow}  "
              f"(actual={ev['actual']:.3f}s, target={ev['target']:.3f}s)")

    # Final convergence stats
    last_diffs = [h[1] for h in history[-10:]]
    converged_diff = round(sum(last_diffs) / len(last_diffs), 1)
    print(f"\n  Final 10 blocks avg difficulty : {converged_diff}")
    print(f"  Theoretical ideal difficulty   : "
          f"{math.log(TARGET_BLOCK_TIME * HASH_RATE) / math.log(16):.2f} "
          f"(where 16^d / {HASH_RATE:,} = {TARGET_BLOCK_TIME}s)")


# ---------------------------------------------------------------------------
# Bitcoin comparison table
# ---------------------------------------------------------------------------

def print_bitcoin_comparison():
    banner("How DorianCoin Retargeting Compares to Bitcoin")
    rows = [
        ("Parameter",            "Bitcoin",           "DorianCoin (default)"),
        ("-" * 22,               "-" * 18,            "-" * 22),
        ("Retarget interval",    "2,016 blocks",      "10 blocks"),
        ("Target block time",    "600 s (10 min)",    "10 s"),
        ("Max ratio change",     "4x per period",     "4x per period"),
        ("Difficulty unit",      "256-bit target",    "leading zeros (int)"),
        ("Hash function",        "SHA-256d",          "SHA-256"),
        ("Clamping",             "[0.25x, 4x]",       "[0.25x, 4x]"),
        ("Min difficulty",       "1",                 "1 (configurable)"),
    ]
    col_w = [24, 20, 24]
    for row in rows:
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(row, col_w)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    banner("DorianCoin Stage 4 -- Difficulty Retargeting Demo")
    print("""
  The retargeting algorithm ensures DorianCoin maintains its target
  block time even as network hash rate grows or shrinks.

  Core formula:
    ratio        = target_time / actual_time     (clamped to [0.25, 4.0])
    new_difficulty = round(old_difficulty * ratio)
    new_difficulty = clamp(new_difficulty, MIN, MAX)

  If actual < target  ->  ratio > 1  ->  difficulty increases
  If actual > target  ->  ratio < 1  ->  difficulty decreases
    """)

    bc_a = scenario_a()
    bc_b = scenario_b()
    scenario_c()
    print_bitcoin_comparison()

    banner("Stage 4 Complete!")
    print("""
  What we built:
    - Automatic difficulty retargeting in Blockchain._adjust_difficulty()
    - Fires every `retarget_interval` blocks (configurable)
    - Clamped 4x ratio guard (same as Bitcoin)
    - Full retarget_log history on every Blockchain instance
    - New REST endpoint:  GET /difficulty  (retarget status + history)
    - node.py now accepts --retarget-interval and --target-block-time flags

  Quick API test (after starting a node):
    python node.py --port 5000 --difficulty 3 --retarget-interval 5 --target-block-time 2

    curl http://localhost:5000/difficulty
    curl http://localhost:5000/mine     (watch difficulty change after 5 mines)

  Next (Stage 5 -- Persistent Storage):
    - SQLite backend: save chain + wallet to disk on every block
    - Survives node restarts without re-mining
    - Indexes for fast balance / tx lookups
    """)


if __name__ == "__main__":
    main()
