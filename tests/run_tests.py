#!/usr/bin/env python3
"""Tests for the Teanga v0.1 interpreter."""

import sys
import os
import io
import contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from teanga import run_source, Interp, lex, Parser

# ---------- helpers ----------

PASSED = []
FAILED = []

def capture(src: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_source(src)
    return buf.getvalue()

def expect(name: str, src: str, expected_output: str):
    try:
        got = capture(src)
        if got == expected_output:
            PASSED.append(name)
        else:
            FAILED.append((name, expected_output, got, None))
    except Exception as e:
        FAILED.append((name, expected_output, "", e))

def expect_value(name: str, src: str, expected):
    """Evaluate a single expression program and check the final value."""
    try:
        toks = lex(src)
        program = Parser(toks).parse_program()
        result = Interp().run(program)
        if result == expected:
            PASSED.append(name)
        else:
            FAILED.append((name, repr(expected), repr(result), None))
    except Exception as e:
        FAILED.append((name, repr(expected), "", e))

# ---------- tests ----------

expect("hello",
    'print("hi")\n',
    "hi\n")

expect("arithmetic",
    'print(1 + 2 * 3)\n',
    "7\n")

expect("string concat",
    'print("a" + "b")\n',
    "ab\n")

expect("interpolation",
    'val x = 5\nprint("x is $x")\n',
    "x is 5\n")

expect("interpolation expr",
    'print("sum is ${1 + 2}")\n',
    "sum is 3\n")

expect("if-else",
    'print(if (1 < 2) "yes" else "no")\n',
    "yes\n")

expect("val",
    'val x = 42\nprint(x)\n',
    "42\n")

expect("fn call",
    'fn double(x: Number): Number = x * 2\nprint(double(7))\n',
    "14\n")

expect("closure",
    'fn adder(n: Number): Function = { x -> x + n }\nval add3 = adder(3)\nprint(add3(10))\n',
    "13\n")

expect("array literal",
    'print([1, 2, 3])\n',
    "[1, 2, 3]\n")

expect("record literal",
    'val p = { name: "x", age: 1 }\nprint(p.name)\n',
    "x\n")

expect("record shorthand",
    'val name = "Bob"\nval p = { name }\nprint(p.name)\n',
    "Bob\n")

expect("for comprehension",
    'print(for (n in [1, 2, 3]) n * 2)\n',
    "[2, 4, 6]\n")

expect("forEach",
    'forEach([1, 2, 3]) { x -> print(x) }\n',
    "1\n2\n3\n")

expect("map",
    'print(map([1, 2, 3]) { it * 10 })\n',
    "[10, 20, 30]\n")

expect("filter",
    'print(filter([1, 2, 3, 4]) { it > 2 })\n',
    "[3, 4]\n")

expect("fold",
    'print(fold([1, 2, 3, 4], 0) { acc, x -> acc + x })\n',
    "10\n")

expect("when literal",
    'val x = 2\nprint(when (x) {\n  1 -> "one"\n  2 -> "two"\n  else -> "other"\n})\n',
    "two\n")

expect("when type",
    'fn t(v: Object): String = when (v) {\n'
    '  is Number -> "num"\n  is String -> "str"\n  else -> "?"\n}\n'
    'print(t(1))\nprint(t("x"))\nprint(t(true))\n',
    "num\nstr\n?\n")

expect("when record",
    'val r = { tag: "ok", value: 42 }\n'
    'print(when (r) {\n  is { tag: "ok", value } -> "ok ${show(value)}"\n'
    '  else -> "no"\n})\n',
    "ok 42\n")

expect("structural equality",
    'print({ a: 1, b: 2 } == { b: 2, a: 1 })\n'
    'print([1, 2, 3] == [1, 2, 3])\n'
    'print({ a: 1 } == { a: 2 })\n',
    "true\ntrue\nfalse\n")

expect("trailing lambda with single it",
    'print(map([1, 2, 3]) { it * it })\n',
    "[1, 4, 9]\n")

expect("nested calls",
    'print(map(filter([1, 2, 3, 4]) { it > 1 }) { it * 10 })\n',
    "[20, 30, 40]\n")

expect("recursion",
    'fn fact(n: Number): Number = if (n <= 1) 1 else n * fact(n - 1)\n'
    'print(fact(5))\n',
    "120\n")

expect("try/catch",
    'fn boom(): Number = throw "oops"\n'
    'val r = try boom() catch (e) "caught: $e"\n'
    'print(r)\n',
    "caught: oops\n")

expect("do block",
    'val r = do {\n  val a = 1\n  val b = 2\n  a + b\n}\n'
    'print(r)\n',
    "3\n")

expect("null and equality",
    'print(null == null)\nprint(null == 0)\n',
    "true\nfalse\n")

expect("modulo",
    'print(7 % 3)\nprint(10 % 5)\n',
    "1\n0\n")

expect("typeof",
    'print(typeof(1))\nprint(typeof("x"))\nprint(typeof([]))\nprint(typeof({}))\nprint(typeof(null))\n',
    "Number\nString\nArray\nObject\nNull\n")

# ---------- summary ----------

print(f"\nPassed: {len(PASSED)}")
print(f"Failed: {len(FAILED)}")
for name, exp, got, err in FAILED:
    print(f"\n  FAIL: {name}")
    if err:
        print(f"    error: {err!r}")
    print(f"    expected: {exp!r}")
    print(f"    got:      {got!r}")

sys.exit(0 if not FAILED else 1)
