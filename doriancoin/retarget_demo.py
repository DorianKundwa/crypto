"""
retarget_demo.py -- DorianCoin Stage 4: Difficulty Retargeting Demo
====================================================================
Demonstrates the automatic difficulty adjustment algorithm across
three scenarios — all complete in under 10 seconds total.

  A. Blocks too FAST  -> difficulty increases  (diff 2 -> 4, capped)
  B. Blocks too SLOW  -> difficulty decreases  (diff 3 -> 1)
  C. Convergence      -> virtual timestamps, 50 retarget periods

Run:
    python -u doriancoin/retarget_demo.py   (from repo root)
    python -u retarget_demo.py              (from doriancoin/)
"""

import sys
import time
import math
from blockchain import Blockchain

DIVIDER = "=" * 62
SUBDIV  = "-" * 62


def banner(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)
    sys.stdout.flush()


def sub(title: str) -> None:
    print(f"\n{SUBDIV}")
    print(f"  {title}")
    print(SUBDIV)
    sys.stdout.flush()


def mine_n(bc: Blockchain, n: int) -> list:
    """Mine n blocks; return list of (index, elapsed_s, nonce)."""
    results = []
    for _ in range(n):
        # peek at retarget log length before mining
        log_before = len(bc.retarget_log)

        t0    = time.perf_counter()
        block = bc.mine_pending_transactions("DEMO_MINER")
        elapsed = time.perf_counter() - t0

        retargeted = len(bc.retarget_log) > log_before
        marker     = "*" if retargeted else " "
        tag = (f"  [RETARGET -> diff {bc.retarget_log[-1]['new_difficulty']}]"
               if retargeted and bc.retarget_log[-1]["changed"] else "")

        print(f"  {marker} Block {block.index:>3}  "
              f"diff={bc.difficulty if not retargeted else bc.retarget_log[-1]['old_difficulty']}"
              f"  nonce={block.nonce:>8,}  {elapsed:.4f}s{tag}")
        sys.stdout.flush()
        results.append((block.index, elapsed, block.nonce))
    return results


def print_retarget_event(ev: dict) -> None:
    direction = ("UP  ^" if ev["new_difficulty"] > ev["old_difficulty"] else
                 "DOWN v" if ev["new_difficulty"] < ev["old_difficulty"] else
                 "no change =")
    approx = 16 ** ev["new_difficulty"]
    print(f"\n  >> RETARGET at block {ev['block_height']} <<")
    print(f"     Actual time for window : {ev['actual_time']:.4f}s")
    print(f"     Target time for window : {ev['target_time']:.4f}s")
    print(f"     Raw ratio              : {ev['raw_ratio']:.2f}x  "
          f"(clamped to {ev['ratio']:.2f}x)")
    print(f"     Difficulty             : {ev['old_difficulty']} -> "
          f"{ev['new_difficulty']}  [{direction}]")
    print(f"     Next block expected ~  : ~{approx:,} hashes")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Scenario A — too FAST
# ---------------------------------------------------------------------------

def scenario_a():
    sub("Scenario A: Blocks Too FAST  (difficulty should go UP)")
    print("""
  Config:
    starting difficulty : 2     (~256 expected hashes / block)
    retarget interval   : 5 blocks
    target block time   : 5.0 s / block
    MAX difficulty cap  : 4     (so we don't get stuck mining diff=6+)

  At diff=2 Python mines in ~0.001s << 5s target.
  After 5 blocks: actual~0.01s, target=25s  =>  ratio=4x (clamped)
  Expected: round(2 * 4) = 8, but capped at MAX=4
    """)

    bc = Blockchain(
        difficulty        = 2,
        retarget_interval = 5,
        target_block_time = 5.0,
        min_difficulty    = 1,
        max_difficulty    = 4,   # cap so post-retarget blocks stay fast
    )
    print(f"  Chain starts at difficulty={bc.difficulty}  "
          f"(next retarget at block {bc.retarget_interval})\n")

    results = mine_n(bc, 5)

    if bc.retarget_log:
        print_retarget_event(bc.retarget_log[-1])

    # Mine 3 more at new difficulty to compare timings
    print(f"\n  Mining 3 more blocks at new difficulty={bc.difficulty}...")
    after = mine_n(bc, 3)

    avg_before = sum(r[1] for r in results) / len(results)
    avg_after  = sum(r[1] for r in after)   / len(after)
    factor     = avg_after / avg_before if avg_before > 0 else float("inf")
    print(f"\n  Avg block time  BEFORE retarget : {avg_before:.4f}s  (diff=2)")
    print(f"  Avg block time  AFTER  retarget : {avg_after:.4f}s  (diff={bc.difficulty})")
    print(f"  Blocks got {factor:.1f}x HARDER  (as expected)\n")
    return bc


# ---------------------------------------------------------------------------
# Scenario B — too SLOW
# ---------------------------------------------------------------------------

def scenario_b():
    sub("Scenario B: Blocks Too SLOW  (difficulty should go DOWN)")
    print("""
  Config:
    starting difficulty : 3     (~4,096 expected hashes / block)
    retarget interval   : 4 blocks
    target block time   : 0.0001 s / block  (sub-ms target!)

  At diff=3 Python mines in ~0.005-0.05s >> 0.0001s target.
  After 4 blocks: actual >> target  =>  raw ratio << 0.25, clamped to 0.25x
  Expected: round(3 * 0.25) = 1  (MIN difficulty)
    """)

    bc = Blockchain(
        difficulty        = 3,
        retarget_interval = 4,
        target_block_time = 0.0001,
        min_difficulty    = 1,
        max_difficulty    = 6,
    )
    print(f"  Chain starts at difficulty={bc.difficulty}\n")

    results = mine_n(bc, 4)

    if bc.retarget_log:
        print_retarget_event(bc.retarget_log[-1])

    print(f"\n  Mining 3 more blocks at new difficulty={bc.difficulty} (should be instant)...")
    after = mine_n(bc, 3)

    avg_before = sum(r[1] for r in results) / len(results)
    avg_after  = sum(r[1] for r in after)   / len(after)
    factor     = avg_before / avg_after if avg_after > 0 else float("inf")
    print(f"\n  Avg block time  BEFORE retarget : {avg_before:.5f}s  (diff=3)")
    print(f"  Avg block time  AFTER  retarget : {avg_after:.6f}s  (diff={bc.difficulty})")
    print(f"  Blocks got {factor:.0f}x FASTER  (as expected)\n")
    return bc


# ---------------------------------------------------------------------------
# Scenario C — Convergence with virtual timestamps
# ---------------------------------------------------------------------------

def scenario_c():
    sub("Scenario C: Convergence Simulation  (virtual timestamps)")
    print("""
  No real mining here -- we inject fake block timestamps so we can
  watch the algorithm across 50 retarget periods in milliseconds.

  Config:
    starting difficulty : 1
    retarget interval   : 5 virtual blocks
    target block time   : 1.0 s / block
    simulated hash rate : 50,000 hashes / second
    """)

    TARGET    = 1.0      # seconds per block
    INTERVAL  = 5
    MIN_D, MAX_D = 1, 8
    HASH_RATE = 50_000   # hashes/sec on this machine

    diff     = 1
    ts       = 0.0       # virtual clock (seconds)
    chain_ts = [0.0]     # timestamp of each virtual block

    print(f"  {'Block':>6}  {'Diff':>5}  {'Sim time/blk':>14}  {'Event'}")
    print(f"  {'-'*6}  {'-'*5}  {'-'*14}  {'-'*36}")

    retarget_events = []
    history = []

    for i in range(1, 56):
        # Simulate how long this block takes at current difficulty
        expected_hashes = 16 ** diff
        block_time      = expected_hashes / HASH_RATE
        ts             += block_time
        chain_ts.append(ts)
        history.append((i, diff, block_time))

        label = ""
        height = len(chain_ts) - 1   # 0-indexed genesis in chain_ts[0]

        if height >= INTERVAL and height % INTERVAL == 0:
            actual = chain_ts[-1] - chain_ts[-INTERVAL - 1]
            target = INTERVAL * TARGET

            actual  = max(actual, 1e-9)
            raw_r   = target / actual
            ratio   = max(0.25, min(4.0, raw_r))
            new_d   = max(MIN_D, min(MAX_D, round(diff * ratio)))

            arrow = "^" if new_d > diff else ("v" if new_d < diff else "=")
            label = (f"RETARGET {diff}->{new_d}{arrow}  "
                     f"(actual={actual:.3f}s  target={target:.1f}s  "
                     f"ratio={ratio:.2f}x)")
            retarget_events.append(dict(block=height, old=diff, new=new_d,
                                        actual=actual, target=target, ratio=ratio))
            diff = new_d

        print(f"  {i:>6}  {history[-1][1]:>5}  {block_time:>12.5f}s  {label}")
        sys.stdout.flush()

    print(f"\n  --- Retarget summary ({len(retarget_events)} events) ---")
    for ev in retarget_events:
        arrow = "^" if ev["new"] > ev["old"] else ("v" if ev["new"] < ev["old"] else "=")
        print(f"    Block {ev['block']:>3}:  diff {ev['old']}->{ev['new']}{arrow}  "
              f"actual={ev['actual']:.3f}s  ratio={ev['ratio']:.2f}x")

    last_10_diffs = [h[1] for h in history[-10:]]
    avg_final_diff = sum(last_10_diffs) / len(last_10_diffs)
    ideal_diff = math.log(TARGET * HASH_RATE) / math.log(16)
    print(f"\n  Final 10-block avg difficulty : {avg_final_diff:.1f}")
    print(f"  Theoretical ideal difficulty  : {ideal_diff:.2f}  "
          f"(where 16^d / {HASH_RATE:,} hash/s = {TARGET}s)")
    converged = abs(avg_final_diff - ideal_diff) < 1.0
    print(f"  Converged within 1 unit       : {'YES' if converged else 'NO'}")


# ---------------------------------------------------------------------------
# Bitcoin comparison
# ---------------------------------------------------------------------------

def print_comparison():
    banner("DorianCoin vs Bitcoin: Retargeting Comparison")
    rows = [
        ("Parameter",            "Bitcoin",           "DorianCoin (default)"),
        ("-" * 24,               "-" * 18,            "-" * 24),
        ("Retarget interval",    "2,016 blocks",      "10 blocks"),
        ("Target block time",    "600 s (10 min)",    "10.0 s"),
        ("Max ratio change",     "4x per period",     "4x per period"),
        ("Difficulty precision", "256-bit target",    "integer leading zeros"),
        ("Hash function",        "SHA-256d",          "SHA-256"),
        ("Adjustment clamp",     "[0.25x, 4x]",       "[0.25x, 4x]"),
        ("Min difficulty",       "genesis target",    "1 (configurable)"),
        ("New API endpoint",     "N/A",               "GET /difficulty"),
    ]
    col_w = [26, 20, 26]
    for row in rows:
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(row, col_w)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    banner("DorianCoin Stage 4 -- Difficulty Retargeting Demo")
    print("""
  The retargeting algorithm keeps DorianCoin's block time stable
  even as hash rate grows or shrinks.

  Core formula:
    ratio          = target_time / actual_time    (clamped [0.25, 4.0])
    new_difficulty = round(old_difficulty * ratio)
    new_difficulty = clamp(new_difficulty, MIN, MAX)

  ratio > 1  -> blocks came TOO FAST -> difficulty INCREASES
  ratio < 1  -> blocks came TOO SLOW -> difficulty DECREASES
    """)

    scenario_a()
    scenario_b()
    scenario_c()
    print_comparison()

    banner("Stage 4 Complete!")
    print("""
  What we built in Stage 4:
    [OK] Blockchain._adjust_difficulty()  -- fires every N blocks
    [OK] ratio = target_time / actual_time, clamped to [0.25x, 4x]
    [OK] retarget_log[]                   -- full history on every chain
    [OK] Blockchain.retarget_status()     -- snapshot for API
    [OK] GET /difficulty                  -- new REST endpoint
    [OK] node.py --retarget-interval / --target-block-time  CLI flags

  Quick API test:
    python doriancoin/node.py --port 5000 --difficulty 2 \\
           --retarget-interval 5 --target-block-time 2

    curl http://localhost:5000/difficulty
    curl http://localhost:5000/mine        (repeat 5x, watch difficulty change)

  Next -> Stage 5: Persistent Storage (SQLite)
    """)


if __name__ == "__main__":
    main()
