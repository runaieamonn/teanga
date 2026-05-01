# Teanga — Language Specification (v0.1)

> Lisp's uniformity in a familiar suit. Pure, lazy, statically typed,
> designed for industrial-scale teams.

## Design principles

1. **Uniformity.** Every construct is an expression that returns a value.
2. **Purity by default.** No mutation. Single assignment. Lazy evaluation.
3. **Effects are values.** Side effects live inside `IO`, executed by a runtime.
4. **Familiarity over novelty.** Kotlin-shaped syntax; no surprises in the parser.
5. **Readable at scale.** No metaprogramming, stable grammar, mandatory LSP.

## Syntax (Kotlin-flavored)

```
namespace todo.cli

import std.io

public fn main(): IO<Unit> = do {
  val args = readArgs()
  when (args[0]) {
    "add"  -> addTodo(args[1])
    "list" -> listTodos()
    null   -> print("usage: todo [add|list]")
    else   -> throw InvalidCommand("unknown: ${args[0]}")
  }
}

fn addTodo(text: String): IO<Unit> = do {
  val todos = loadTodos()
  saveTodos(todos + [{ id: nextId(todos), text: text, done: false }])
}

fn listTodos(): IO<Unit> = do {
  val todos = loadTodos()
  forEach(todos) { t ->
    print("${if (t.done) "x" else " "} ${t.id}: ${t.text}")
  }
}
```

## Core rules

- **No assignment.** `val` binds once.
- **`if` requires `else`.** A conditional without both branches is a compile error.
- **`for` is comprehension.** `for (x in xs) e` has type `[E]`. The body is a
  single expression; for multiple statements, use `for (x in xs) do { ... }`.
  To run effects per element, use `forEach` (a stdlib function), not `for`.
- **Definitions evaluate to `Unit`.**
- **Lazy.** Values are computed on demand. Effects in `IO` are executed eagerly
  by the runtime when the `IO` is run.

## Operators

| Group | Operators |
|---|---|
| Arithmetic | `+`, `-`, `*`, `/`, `%` |
| Comparison | `<`, `>`, `<=`, `>=`, `==`, `!=` |
| Logical | `&&`, `\|\|`, `!` |
| Nullable | `?.` (safe call), `?:` (Elvis) |
| Concat | `+` on `String`, `+` on `[T]` |

Equality (`==` / `!=`) is structural for records and arrays.

## Types

| Category | Form | Notes |
|---|---|---|
| Primitives | `Number`, `String`, `Bool`, `Null` | `Number` is f64. |
| Arrays | `[T]` | Lazy sequences. |
| Records | `{ k1: T1, k2: T2 }` | **Structural.** No declaration required. Shorthand `{ name }` means `{ name: name }`. |
| Functions | `T -> U` | First-class, curried. |
| Effects | `IO<T>` | Description of an effectful computation. |
| Nullable | `T?` | Kotlin-style. `?.`, `?:`, smart casts. No `Maybe`. |
| Generics | `<T, U>` | Kotlin-style angle brackets. |

**Equality is structural** for records and arrays. Lazy values are forced
before comparison.

**No sum types.** Errors propagate via exceptions. (Re-evaluate at v0.2.)

## Lambdas and method-style calls

```
{ x -> x + 1 }                    // single parameter
{ x, y -> x + y }                 // multiple parameters
{ it * 2 }                        // single param, implicitly named `it`
xs.map { it * 2 }                 // trailing-lambda sugar
xs.fold(0) { acc, x -> acc + x }  // trailing lambda after parens
```

`x.f(args)` first looks for `f` as a record field on `x`. If not found and `f`
is a function in scope, it desugars to `f(x, args)`. This lets `xs.map { ... }`
and `map(xs, ...)` mean the same thing without requiring user-defined methods.

## Effects and concurrency

- Side effects are `IO<T>` values; only the runtime runs them.
- `do { ... }` is sugar for `flatMap` chains, **only** for `IO`.
- **Structured concurrency.** A `do` block is also a task scope; child tasks
  cannot outlive their parent. Primitives: `parallel`, `race`, `forEachPar`.
- **Unchecked exceptions.** `throw` and `try`/`catch`. Not in types.

## Modules

- Directory hierarchy = namespace (`src/foo/bar.tng` → `foo.bar`).
- `public` keyword exports a definition. Default is private.
- `import foo.bar.Baz` brings names in.

## Targets

- **JVM** (primary): bytecode, virtual threads.
- **Native** via LLVM: standalone binaries.
- **WASM**: browser and Wasi.

Stdlib partitioned into `common` (everywhere) and platform modules.

## Pattern matching

`when` matches on:
- Literals: `1`, `"ok"`, `true`, `null`
- Record shapes: `{ tag: "ok", value }`
- Array shapes: `[]`, `[x, ...rest]`
- Type guards: `is Number`, `is String`, `is Bool`, `is Null`,
  `is Array`, `is Object`, `is Function`, `is IO`

## Tooling commitments

- LSP from day one.
- Mandatory tail-call optimization on every target.
- Single multi-target build tool with declarative manifests.

## Open items (v0.1 → v0.2)

- Whether "no sums" survives real code (~60% odds re-added).
- Concrete `BigInt` / `BigDecimal` story for f64 limits.
- FFI shape per target.
- Package manager design.
