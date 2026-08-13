#!/usr/bin/env python3
"""
commit.py -- Quick commit + push helper for DorianCoin development.
Usage:
    python commit.py "your message"           # commit with custom message
    python commit.py                          # auto-message: "stage: auto-commit"
"""
import sys
import subprocess
import datetime

msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else \
      f"chore: auto-commit {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (result.stdout + result.stderr).strip()
    if out:
        print(out)
    return result.returncode

print(f"\n  Committing: {msg!r}\n")
run("git add -A")
rc = run(f'git commit -m "{msg}"')
if rc == 0:
    run("git push origin master")
    print("\n  [OK] Pushed to https://github.com/DorianKundwa/crypto.git")
else:
    print("\n  [!!] Nothing to commit or commit failed.")
