#!/usr/bin/env python3
"""Self-hosting test: the Teanga lexer (teanga.tng) must produce the same
token stream as the reference Python lexer (teanga.py --lex).

Limited to programs that fit within both implementations' featureset:
no string interpolation and no block comments. Without TCO, neither can
the Teanga lexer chew through inputs much larger than ~1500 tokens.
"""

import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEANGA = os.path.join(ROOT, "teanga.py")
SELF_HOST = os.path.join(ROOT, "teanga.tng")

# Inputs that don't use interpolation or block comments.
INPUTS = [
    "examples/closures.tng",
    "examples/fizzbuzz.tng",
]

def run(args):
    return subprocess.run(
        ["python3"] + args, capture_output=True, text=True, cwd=ROOT, check=False,
    )

def main():
    failed = 0
    for relpath in INPUTS:
        py = run([TEANGA, "--lex", relpath])
        tn = run([TEANGA, SELF_HOST, relpath])
        if py.returncode != 0:
            print(f"FAIL {relpath}: python lexer errored: {py.stderr.strip()}")
            failed += 1; continue
        if tn.returncode != 0:
            print(f"FAIL {relpath}: teanga lexer errored: {tn.stderr.strip()}")
            failed += 1; continue
        if py.stdout != tn.stdout:
            print(f"FAIL {relpath}: token streams differ")
            print("--- expected (python) ---")
            print(py.stdout[:400])
            print("--- got (teanga.tng) ---")
            print(tn.stdout[:400])
            failed += 1; continue
        n = py.stdout.count("\n")
        print(f"PASS {relpath} ({n} tokens)")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
