# Teanga

> Lisp's uniformity in a familiar suit. Pure, lazy, statically typed,
> designed for industrial-scale teams.

See [SPEC.md](SPEC.md) for the full v0.1 specification.

## Status

**v0.1 — tree-walking interpreter.** A useful subset of the language,
implemented in Python for quick iteration. The full spec (laziness, IO
monad, static types, multi-target compilation) is the goal; this is the
stepping stone.

### What works

- Literals: `Number` (f64), `String`, `Bool`, `null`, arrays, records
- `val` bindings, `fn` declarations, lambdas, closures
- Trailing-lambda sugar: `list.map { it * 2 }`
- String interpolation: `"hello $name"` and `"${1 + 2}"`
- `if` / `else` and `when` (literal / type / record-shape patterns)
- `for` comprehensions returning arrays
- `do` blocks (eager sequencing)
- `throw` / `try` / `catch`
- Structural equality on records and arrays
- Built-ins: `print`, `length`, `range`, `map`, `filter`, `fold`,
  `forEach`, `typeof`, `keys`, `show`, `readLine`

### What's deferred

- Lazy evaluation (currently eager)
- Real `IO` monad (currently `do` is plain sequencing)
- Static type checking (annotations parsed but ignored)
- Generics (parsed but ignored)
- Modules / namespaces / imports (parsed but ignored)
- Sum types, nullable smart casts, pattern exhaustiveness
- Tail-call optimization
- Multi-target compilation (JVM, native, WASM)

## Run

```bash
python3 teanga.py examples/hello.tng
python3 teanga.py examples/fizzbuzz.tng
python3 tests/run_tests.py     # 29 tests
```

## A taste

```
fn fizzbuzz(n: Number): String =
  if (n % 15 == 0) "FizzBuzz"
  else if (n % 3 == 0) "Fizz"
  else if (n % 5 == 0) "Buzz"
  else show(n)

forEach(range(1, 21)) { n -> print(fizzbuzz(n)) }
```

```
fn handleResult(r: Object): String = when (r) {
  is { tag: "ok", value }    -> "ok: ${show(value)}"
  is { tag: "err", message } -> "error: $message"
  else                       -> "unknown"
}
```

## Layout

```
teanga.py            single-file interpreter (lexer + parser + evaluator)
SPEC.md              language specification (v0.1)
examples/*.tng       runnable example programs
tests/run_tests.py   interpreter test suite
```
