#!/usr/bin/env python3
"""Teanga v0.1 — tree-walking interpreter.

A subset of the language specified in SPEC.md. Eager evaluation; type
annotations are parsed but ignored. No modules, no generics, no laziness,
no IO monad — `do` is plain sequencing.

Usage: ./teanga.py <file.tng>
"""

from __future__ import annotations
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

# ============================================================
# LEXER
# ============================================================

KEYWORDS = {
    "val", "fn", "if", "else", "when", "is", "do", "for", "in",
    "true", "false", "null", "return", "public", "namespace", "import",
    "throw", "try", "catch",
}

@dataclass
class Tok:
    kind: str
    value: Any
    line: int

def lex(src: str) -> list[Tok]:
    toks: list[Tok] = []
    i, line = 0, 1
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c.isspace():
            i += 1; continue
        # line comment
        if c == "/" and i + 1 < n and src[i+1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        # block comment
        if c == "/" and i + 1 < n and src[i+1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i+1] == "/"):
                if src[i] == "\n": line += 1
                i += 1
            i += 2
            continue
        # number
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            toks.append(Tok("NUM", float(src[i:j]), line))
            i = j; continue
        # string with interpolation
        if c == '"':
            i += 1
            parts: list[tuple[str, Any]] = []
            buf = ""
            while i < n and src[i] != '"':
                if src[i] == "\\" and i + 1 < n:
                    esc = src[i+1]
                    buf += {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "$": "$"}.get(esc, esc)
                    i += 2
                elif src[i] == "$" and i + 1 < n and (src[i+1].isalpha() or src[i+1] == "_" or src[i+1] == "{"):
                    if buf:
                        parts.append(("str", buf)); buf = ""
                    i += 1
                    if src[i] == "{":
                        i += 1
                        depth, start = 1, i
                        while i < n and depth > 0:
                            if src[i] == "{": depth += 1
                            elif src[i] == "}": depth -= 1
                            if depth > 0: i += 1
                        parts.append(("expr", src[start:i]))
                        i += 1
                    else:
                        start = i
                        while i < n and (src[i].isalnum() or src[i] == "_"):
                            i += 1
                        parts.append(("expr", src[start:i]))
                else:
                    buf += src[i]; i += 1
            if buf:
                parts.append(("str", buf))
            i += 1  # closing "
            if len(parts) == 1 and parts[0][0] == "str":
                toks.append(Tok("STR", parts[0][1], line))
            elif not parts:
                toks.append(Tok("STR", "", line))
            else:
                toks.append(Tok("STR_INTERP", parts, line))
            continue
        # ident / keyword
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            if word == "true":   toks.append(Tok("BOOL", True, line))
            elif word == "false": toks.append(Tok("BOOL", False, line))
            elif word == "null":  toks.append(Tok("NULL", None, line))
            elif word in KEYWORDS: toks.append(Tok("KW", word, line))
            else:                  toks.append(Tok("ID", word, line))
            i = j; continue
        # multi-char operators
        two = src[i:i+2]
        if two in ("==", "!=", "<=", ">=", "&&", "||", "->", "?:", "?."):
            toks.append(Tok("OP", two, line)); i += 2; continue
        if c in "+-*/%<>=!?":
            toks.append(Tok("OP", c, line)); i += 1; continue
        if c in "(){}[],:;.":
            toks.append(Tok("PUNCT", c, line)); i += 1; continue
        raise SyntaxError(f"Line {line}: unexpected {c!r}")
    toks.append(Tok("EOF", None, line))
    return toks


# ============================================================
# AST
# ============================================================

@dataclass
class Num:    v: float
@dataclass
class Str:    v: str
@dataclass
class Bool:   v: bool
@dataclass
class Null:   pass
@dataclass
class StrInterp: parts: list  # [("str", text) | ("expr", AST)]
@dataclass
class Var:    name: str
@dataclass
class Arr:    items: list
@dataclass
class Rec:    fields: list  # [(name, expr)]
@dataclass
class Field:  obj: Any; name: str
@dataclass
class Index:  obj: Any; idx: Any
@dataclass
class Call:   callee: Any; args: list
@dataclass
class Lam:    params: list; body: Any
@dataclass
class IfE:    cond: Any; then: Any; else_: Any
@dataclass
class WhenE:  subject: Any; arms: list  # [(pattern, body)]
@dataclass
class ForE:   var: str; iter: Any; body: Any
@dataclass
class DoE:    stmts: list
@dataclass
class Bin:    op: str; l: Any; r: Any
@dataclass
class Una:    op: str; e: Any
@dataclass
class Val:    name: str; expr: Any
@dataclass
class Fn:     name: str; params: list; body: Any
@dataclass
class Throw:  expr: Any
@dataclass
class TryE:   body: Any; catch_var: str; handler: Any

# Patterns for `when`
@dataclass
class PLit:   v: Any            # 1, "x", true, null
@dataclass
class PElse:  pass
@dataclass
class PType:  name: str         # is String, is Number, ...
@dataclass
class PRec:   fields: list      # [(key, PLit | PBind)]
@dataclass
class PBind:  name: str         # binding identifier inside a record pattern


# ============================================================
# PARSER
# ============================================================

class Parser:
    def __init__(self, toks: list[Tok]):
        self.toks = toks
        self.pos = 0

    def peek(self, off: int = 0) -> Tok:
        return self.toks[min(self.pos + off, len(self.toks) - 1)]

    def adv(self) -> Tok:
        t = self.toks[self.pos]; self.pos += 1; return t

    def check(self, kind: str, value: Any = None) -> bool:
        t = self.peek()
        if t.kind != kind: return False
        return value is None or t.value == value

    def match(self, kind: str, value: Any = None) -> Tok | None:
        return self.adv() if self.check(kind, value) else None

    def expect(self, kind: str, value: Any = None) -> Tok:
        if self.check(kind, value):
            return self.adv()
        t = self.peek()
        raise SyntaxError(f"Line {t.line}: expected {kind} {value!r}, got {t.kind} {t.value!r}")

    # ---- top-level ----

    def parse_program(self) -> list:
        out = []
        while not self.check("EOF"):
            stmt = self.parse_top()
            if stmt is not None:
                out.append(stmt)
        return out

    def parse_top(self):
        # ignore namespace/import declarations for v0.1
        if self.match("KW", "namespace"):
            self.expect("ID")
            while self.match("PUNCT", "."):
                self.expect("ID")
            return None
        if self.match("KW", "import"):
            self.expect("ID")
            while self.match("PUNCT", "."):
                self.expect("ID")
            return None
        # `public` is just a hint for v0.1
        self.match("KW", "public")
        return self.parse_stmt()

    def parse_stmt(self):
        if self.check("KW", "val"):
            return self.parse_val()
        if self.check("KW", "fn"):
            return self.parse_fn()
        return self.parse_expr()

    def parse_val(self):
        self.expect("KW", "val")
        name = self.expect("ID").value
        if self.match("PUNCT", ":"):
            self.skip_type()
        self.expect("OP", "=")
        return Val(name, self.parse_expr())

    def parse_fn(self):
        self.expect("KW", "fn")
        name = self.expect("ID").value
        # optional generics: <T, U>
        if self.match("OP", "<"):
            depth = 1
            while depth:
                t = self.adv()
                if t.kind == "OP" and t.value == "<": depth += 1
                elif t.kind == "OP" and t.value == ">": depth -= 1
        self.expect("PUNCT", "(")
        params: list[str] = []
        if not self.check("PUNCT", ")"):
            params.append(self.parse_param())
            while self.match("PUNCT", ","):
                params.append(self.parse_param())
        self.expect("PUNCT", ")")
        if self.match("PUNCT", ":"):
            self.skip_type()
        self.expect("OP", "=")
        return Fn(name, params, self.parse_expr())

    def parse_param(self) -> str:
        name = self.expect("ID").value
        if self.match("PUNCT", ":"):
            self.skip_type()
        return name

    def skip_type(self):
        """Consume tokens that make up a type expression. Types are ignored in v0.1."""
        depth_paren = depth_brack = depth_brace = depth_angle = 0
        while True:
            t = self.peek()
            if t.kind == "EOF": return
            if t.kind == "OP" and t.value == "=" and depth_paren == 0 and depth_brack == 0 and depth_brace == 0 and depth_angle == 0:
                return
            if t.kind == "PUNCT" and t.value in (",", ")") and depth_paren == 0 and depth_brack == 0 and depth_brace == 0 and depth_angle == 0:
                return
            if t.kind == "PUNCT":
                if t.value == "(": depth_paren += 1
                elif t.value == ")": depth_paren -= 1
                elif t.value == "[": depth_brack += 1
                elif t.value == "]": depth_brack -= 1
                elif t.value == "{": depth_brace += 1
                elif t.value == "}": depth_brace -= 1
            elif t.kind == "OP":
                if t.value == "<": depth_angle += 1
                elif t.value == ">": depth_angle -= 1
            self.adv()
            if depth_paren < 0 or depth_brack < 0 or depth_brace < 0:
                # we backed out of a containing structure
                self.pos -= 1
                return

    # ---- expressions ----

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        l = self.parse_and()
        while self.match("OP", "||"):
            l = Bin("||", l, self.parse_and())
        return l

    def parse_and(self):
        l = self.parse_eq()
        while self.match("OP", "&&"):
            l = Bin("&&", l, self.parse_eq())
        return l

    def parse_eq(self):
        l = self.parse_cmp()
        while True:
            if self.match("OP", "=="): l = Bin("==", l, self.parse_cmp())
            elif self.match("OP", "!="): l = Bin("!=", l, self.parse_cmp())
            else: break
        return l

    def parse_cmp(self):
        l = self.parse_add()
        while True:
            if   self.match("OP", "<="): l = Bin("<=", l, self.parse_add())
            elif self.match("OP", ">="): l = Bin(">=", l, self.parse_add())
            elif self.match("OP", "<"):  l = Bin("<",  l, self.parse_add())
            elif self.match("OP", ">"):  l = Bin(">",  l, self.parse_add())
            else: break
        return l

    def parse_add(self):
        l = self.parse_mul()
        while True:
            if self.match("OP", "+"): l = Bin("+", l, self.parse_mul())
            elif self.match("OP", "-"): l = Bin("-", l, self.parse_mul())
            else: break
        return l

    def parse_mul(self):
        l = self.parse_unary()
        while True:
            if self.match("OP", "*"): l = Bin("*", l, self.parse_unary())
            elif self.match("OP", "/"): l = Bin("/", l, self.parse_unary())
            elif self.match("OP", "%"): l = Bin("%", l, self.parse_unary())
            else: break
        return l

    def parse_unary(self):
        if self.match("OP", "!"):
            return Una("!", self.parse_unary())
        if self.match("OP", "-"):
            return Una("-", self.parse_unary())
        return self.parse_postfix()

    def parse_postfix(self):
        e = self.parse_atom()
        while True:
            if self.match("PUNCT", "."):
                name = self.expect("ID").value
                e = Field(e, name)
            elif self.match("PUNCT", "("):
                args = []
                if not self.check("PUNCT", ")"):
                    args.append(self.parse_expr())
                    while self.match("PUNCT", ","):
                        args.append(self.parse_expr())
                self.expect("PUNCT", ")")
                # trailing lambda: f(...) { x -> ... }
                if self.is_lambda_block_ahead():
                    args.append(self.parse_lambda_block())
                e = Call(e, args)
            elif self.is_lambda_block_ahead():
                # bare trailing lambda: f { ... }
                e = Call(e, [self.parse_lambda_block()])
            elif self.match("PUNCT", "["):
                idx = self.parse_expr()
                self.expect("PUNCT", "]")
                e = Index(e, idx)
            else:
                break
        return e

    def is_lambda_block_ahead(self) -> bool:
        return self.check("PUNCT", "{")

    def parse_lambda_block(self):
        # { params -> body }   or   { body }   (with implicit `it`)
        self.expect("PUNCT", "{")
        # try to parse `params ->`
        save = self.pos
        params: list[str] = []
        is_lambda = False
        if self.check("ID"):
            params.append(self.adv().value)
            while self.match("PUNCT", ","):
                if not self.check("ID"):
                    self.pos = save
                    params = []
                    break
                params.append(self.adv().value)
            if self.match("OP", "->"):
                is_lambda = True
            else:
                self.pos = save
                params = []
        if not is_lambda:
            params = ["it"]
        body_stmts = self.parse_block_body()
        self.expect("PUNCT", "}")
        body = body_stmts[0] if len(body_stmts) == 1 else DoE(body_stmts)
        return Lam(params, body)

    def parse_block_body(self) -> list:
        stmts = []
        while not self.check("PUNCT", "}") and not self.check("EOF"):
            stmts.append(self.parse_stmt())
            self.match("PUNCT", ";")
        return stmts

    def parse_atom(self):
        t = self.peek()
        # literals
        if t.kind == "NUM":         self.adv(); return Num(t.value)
        if t.kind == "STR":         self.adv(); return Str(t.value)
        if t.kind == "BOOL":        self.adv(); return Bool(t.value)
        if t.kind == "NULL":        self.adv(); return Null()
        if t.kind == "STR_INTERP":
            self.adv()
            parts = []
            for kind, val in t.value:
                if kind == "str":
                    parts.append(("str", val))
                else:
                    sub_toks = lex(val)
                    sub_ast = Parser(sub_toks).parse_expr()
                    parts.append(("expr", sub_ast))
            return StrInterp(parts)
        # parenthesized
        if self.match("PUNCT", "("):
            e = self.parse_expr()
            self.expect("PUNCT", ")")
            return e
        # array literal
        if self.match("PUNCT", "["):
            items = []
            if not self.check("PUNCT", "]"):
                items.append(self.parse_expr())
                while self.match("PUNCT", ","):
                    if self.check("PUNCT", "]"): break
                    items.append(self.parse_expr())
            self.expect("PUNCT", "]")
            return Arr(items)
        # record literal OR lambda block (we choose record only at expression position; bare {} as a lambda is handled in postfix)
        if self.check("PUNCT", "{"):
            return self.parse_record_or_lambda()
        # control-flow expressions
        if self.match("KW", "if"):
            self.expect("PUNCT", "(")
            cond = self.parse_expr()
            self.expect("PUNCT", ")")
            then = self.parse_expr()
            self.expect("KW", "else")
            else_ = self.parse_expr()
            return IfE(cond, then, else_)
        if self.match("KW", "when"):    return self.parse_when()
        if self.match("KW", "for"):     return self.parse_for()
        if self.match("KW", "do"):      return self.parse_do()
        if self.match("KW", "throw"):   return Throw(self.parse_expr())
        if self.match("KW", "try"):     return self.parse_try()
        # identifier
        if t.kind == "ID":
            self.adv(); return Var(t.value)
        raise SyntaxError(f"Line {t.line}: unexpected {t.kind} {t.value!r}")

    def parse_record_or_lambda(self):
        # `{` — could be a record literal or a lambda. Lambdas only show up as
        # trailing arguments (handled in parse_postfix), but a bare `{ x -> x }`
        # at expression position should also work.
        save = self.pos
        self.expect("PUNCT", "{")
        # empty record vs empty body
        if self.match("PUNCT", "}"):
            return Rec([])
        # try lambda: params ->
        if self.check("ID"):
            sub_save = self.pos
            ids = [self.adv().value]
            ok = True
            while self.match("PUNCT", ","):
                if not self.check("ID"): ok = False; break
                ids.append(self.adv().value)
            if ok and self.match("OP", "->"):
                stmts = self.parse_block_body()
                self.expect("PUNCT", "}")
                body = stmts[0] if len(stmts) == 1 else DoE(stmts)
                return Lam(ids, body)
            self.pos = sub_save
        # record literal
        fields = []
        fields.append(self.parse_record_field())
        while self.match("PUNCT", ","):
            if self.check("PUNCT", "}"): break
            fields.append(self.parse_record_field())
        self.expect("PUNCT", "}")
        return Rec(fields)

    def parse_record_field(self):
        if self.check("ID"):
            name = self.adv().value
        elif self.check("STR"):
            name = self.adv().value
        else:
            t = self.peek()
            raise SyntaxError(f"Line {t.line}: expected record field name")
        # shorthand: { name } means { name: name }
        if self.match("PUNCT", ":"):
            return (name, self.parse_expr())
        return (name, Var(name))

    def parse_when(self):
        self.expect("PUNCT", "(")
        subject = self.parse_expr()
        self.expect("PUNCT", ")")
        self.expect("PUNCT", "{")
        arms = []
        while not self.check("PUNCT", "}"):
            pat = self.parse_pattern()
            self.expect("OP", "->")
            body = self.parse_expr()
            self.match("PUNCT", ",")
            arms.append((pat, body))
        self.expect("PUNCT", "}")
        return WhenE(subject, arms)

    def parse_pattern(self):
        if self.match("KW", "else"):
            return PElse()
        if self.match("KW", "is"):
            # is TypeName  OR  is { ... record pattern ... }
            if self.check("PUNCT", "{"):
                return self.parse_record_pattern()
            t = self.expect("ID")
            return PType(t.value)
        # literal patterns
        t = self.peek()
        if t.kind == "NUM":  self.adv(); return PLit(t.value)
        if t.kind == "STR":  self.adv(); return PLit(t.value)
        if t.kind == "BOOL": self.adv(); return PLit(t.value)
        if t.kind == "NULL": self.adv(); return PLit(None)
        raise SyntaxError(f"Line {t.line}: expected pattern, got {t.kind} {t.value!r}")

    def parse_record_pattern(self):
        self.expect("PUNCT", "{")
        fields = []
        if not self.check("PUNCT", "}"):
            fields.append(self.parse_record_pattern_field())
            while self.match("PUNCT", ","):
                if self.check("PUNCT", "}"): break
                fields.append(self.parse_record_pattern_field())
        self.expect("PUNCT", "}")
        return PRec(fields)

    def parse_record_pattern_field(self):
        name = self.expect("ID").value
        if self.match("PUNCT", ":"):
            t = self.peek()
            if t.kind == "NUM":  self.adv(); return (name, PLit(t.value))
            if t.kind == "STR":  self.adv(); return (name, PLit(t.value))
            if t.kind == "BOOL": self.adv(); return (name, PLit(t.value))
            if t.kind == "NULL": self.adv(); return (name, PLit(None))
            if t.kind == "ID":   self.adv(); return (name, PBind(t.value))
            raise SyntaxError(f"Line {t.line}: unsupported pattern in record")
        # shorthand: { value } binds field `value` to name `value`
        return (name, PBind(name))

    def parse_for(self):
        self.expect("PUNCT", "(")
        var = self.expect("ID").value
        self.expect("KW", "in")
        it = self.parse_expr()
        self.expect("PUNCT", ")")
        body = self.parse_expr()
        return ForE(var, it, body)

    def parse_do(self):
        self.expect("PUNCT", "{")
        stmts = self.parse_block_body()
        self.expect("PUNCT", "}")
        return DoE(stmts)

    def parse_try(self):
        body = self.parse_expr()
        self.expect("KW", "catch")
        self.expect("PUNCT", "(")
        var = self.expect("ID").value
        self.expect("PUNCT", ")")
        handler = self.parse_expr()
        return TryE(body, var, handler)


# ============================================================
# RUNTIME
# ============================================================

class Env:
    def __init__(self, parent: "Env | None" = None):
        self.vars: dict[str, Any] = {}
        self.parent = parent

    def get(self, name: str) -> Any:
        if name in self.vars: return self.vars[name]
        if self.parent: return self.parent.get(name)
        raise NameError(f"undefined: {name}")

    def set(self, name: str, value: Any) -> None:
        self.vars[name] = value


class Closure:
    def __init__(self, params: list[str], body: Any, env: Env):
        self.params, self.body, self.env = params, body, env

    def __repr__(self):
        return f"<fn({', '.join(self.params)})>"


class TeangaError(Exception):
    """Raised by `throw`; caught by `try`/`catch`."""
    def __init__(self, value: Any):
        self.value = value
        super().__init__(repr(value))


def type_of(v: Any) -> str:
    if v is None:           return "Null"
    if isinstance(v, bool): return "Bool"
    if isinstance(v, float) or isinstance(v, int): return "Number"
    if isinstance(v, str):  return "String"
    if isinstance(v, list): return "Array"
    if isinstance(v, dict): return "Object"
    if isinstance(v, Closure) or callable(v): return "Function"
    return "Unknown"


def teanga_eq(a: Any, b: Any) -> bool:
    """Structural equality: records compared by their fields, arrays element-wise."""
    if type_of(a) != type_of(b): return False
    if isinstance(a, list):
        return len(a) == len(b) and all(teanga_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(teanga_eq(a[k], b[k]) for k in a)
    return a == b


def show(v: Any) -> str:
    if v is None:               return "null"
    if isinstance(v, bool):     return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, str):      return v
    if isinstance(v, list):     return "[" + ", ".join(show_val(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {show_val(val)}" for k, val in v.items()) + "}"
    return str(v)


def show_val(v: Any) -> str:
    """Like show, but quotes strings (used inside compound values)."""
    if isinstance(v, str): return f'"{v}"'
    return show(v)


# ============================================================
# EVALUATOR
# ============================================================

class Interp:
    def __init__(self):
        self.globals = Env()
        install_builtins(self.globals)

    def run(self, program: list) -> Any:
        # First pass: hoist function declarations.
        for stmt in program:
            if isinstance(stmt, Fn):
                self.globals.set(stmt.name, Closure(stmt.params, stmt.body, self.globals))
        # Second pass: evaluate everything (re-binding fn declarations is fine).
        last = None
        for stmt in program:
            last = self.eval(stmt, self.globals)
        return last

    def eval(self, node: Any, env: Env) -> Any:
        m = getattr(self, f"e_{type(node).__name__}", None)
        if m is None:
            raise RuntimeError(f"no evaluator for {type(node).__name__}")
        return m(node, env)

    # literals
    def e_Num(self, n, env):  return n.v
    def e_Str(self, n, env):  return n.v
    def e_Bool(self, n, env): return n.v
    def e_Null(self, n, env): return None

    def e_StrInterp(self, n, env):
        out = []
        for kind, val in n.parts:
            if kind == "str": out.append(val)
            else:             out.append(show(self.eval(val, env)))
        return "".join(out)

    def e_Var(self, n, env): return env.get(n.name)

    def e_Arr(self, n, env): return [self.eval(x, env) for x in n.items]

    def e_Rec(self, n, env):
        return {k: self.eval(v, env) for k, v in n.fields}

    def e_Field(self, n, env):
        obj = self.eval(n.obj, env)
        if isinstance(obj, dict):
            if n.name in obj: return obj[n.name]
            raise RuntimeError(f"record has no field '{n.name}'")
        # built-in pseudo-method dispatch: x.length, x.toString(), etc.
        builtin = env.get(n.name) if self.has(env, n.name) else None
        if builtin is not None:
            # method-style: x.f(y) -> f(x, y)
            return _BoundMethod(obj, builtin)
        raise RuntimeError(f"no field/method '{n.name}' on {type_of(obj)}")

    def has(self, env: Env, name: str) -> bool:
        try: env.get(name); return True
        except NameError: return False

    def e_Index(self, n, env):
        obj = self.eval(n.obj, env)
        idx = self.eval(n.idx, env)
        if isinstance(obj, list):
            i = int(idx)
            if i < 0 or i >= len(obj): return None
            return obj[i]
        if isinstance(obj, dict):
            return obj.get(idx)
        if isinstance(obj, str):
            i = int(idx)
            if i < 0 or i >= len(obj): return None
            return obj[i]
        raise RuntimeError(f"cannot index {type_of(obj)}")

    def e_Call(self, n, env):
        callee = self.eval(n.callee, env)
        args = [self.eval(a, env) for a in n.args]
        return self.apply(callee, args)

    def apply(self, callee: Any, args: list) -> Any:
        if isinstance(callee, _BoundMethod):
            return self.apply(callee.fn, [callee.receiver] + args)
        if isinstance(callee, Closure):
            if len(args) != len(callee.params):
                raise RuntimeError(f"arity mismatch: expected {len(callee.params)}, got {len(args)}")
            new_env = Env(callee.env)
            for p, a in zip(callee.params, args):
                new_env.set(p, a)
            return self.eval(callee.body, new_env)
        if callable(callee):
            return callee(self, args)
        raise RuntimeError(f"not callable: {callee!r}")

    def e_Lam(self, n, env): return Closure(n.params, n.body, env)

    def e_IfE(self, n, env):
        c = self.eval(n.cond, env)
        return self.eval(n.then if truthy(c) else n.else_, env)

    def e_WhenE(self, n, env):
        subj = self.eval(n.subject, env)
        for pat, body in n.arms:
            bound = match_pattern(pat, subj)
            if bound is not None:
                new_env = Env(env)
                for k, v in bound.items():
                    new_env.set(k, v)
                return self.eval(body, new_env)
        raise RuntimeError(f"no `when` arm matched: {show(subj)}")

    def e_ForE(self, n, env):
        seq = self.eval(n.iter, env)
        if not isinstance(seq, list):
            raise RuntimeError(f"`for` requires Array, got {type_of(seq)}")
        out = []
        for x in seq:
            inner = Env(env)
            inner.set(n.var, x)
            out.append(self.eval(n.body, inner))
        return out

    def e_DoE(self, n, env):
        inner = Env(env)
        last = None
        for s in n.stmts:
            last = self.eval(s, inner)
        return last

    def e_Bin(self, n, env):
        if n.op == "&&":
            l = self.eval(n.l, env)
            return self.eval(n.r, env) if truthy(l) else l
        if n.op == "||":
            l = self.eval(n.l, env)
            return l if truthy(l) else self.eval(n.r, env)
        l = self.eval(n.l, env)
        r = self.eval(n.r, env)
        if n.op == "==":  return teanga_eq(l, r)
        if n.op == "!=":  return not teanga_eq(l, r)
        if n.op == "+":
            if isinstance(l, str) or isinstance(r, str):
                return show(l) + show(r)
            if isinstance(l, list) and isinstance(r, list):
                return l + r
            return l + r
        if n.op == "-":  return l - r
        if n.op == "*":  return l * r
        if n.op == "/":  return l / r
        if n.op == "%":  return l % r
        if n.op == "<":  return l < r
        if n.op == ">":  return l > r
        if n.op == "<=": return l <= r
        if n.op == ">=": return l >= r
        raise RuntimeError(f"unknown binary op {n.op}")

    def e_Una(self, n, env):
        v = self.eval(n.e, env)
        if n.op == "-": return -v
        if n.op == "!": return not truthy(v)
        raise RuntimeError(f"unknown unary op {n.op}")

    def e_Val(self, n, env):
        env.set(n.name, self.eval(n.expr, env))
        return None

    def e_Fn(self, n, env):
        env.set(n.name, Closure(n.params, n.body, env))
        return None

    def e_Throw(self, n, env):
        raise TeangaError(self.eval(n.expr, env))

    def e_TryE(self, n, env):
        try:
            return self.eval(n.body, env)
        except TeangaError as e:
            inner = Env(env)
            inner.set(n.catch_var, e.value)
            return self.eval(n.handler, inner)


@dataclass
class _BoundMethod:
    receiver: Any
    fn: Any


def truthy(v: Any) -> bool:
    if v is None: return False
    if isinstance(v, bool): return v
    return True


def match_pattern(pat: Any, v: Any) -> dict | None:
    if isinstance(pat, PElse):
        return {}
    if isinstance(pat, PLit):
        return {} if teanga_eq(pat.v, v) else None
    if isinstance(pat, PType):
        return {} if type_of(v) == pat.name else None
    if isinstance(pat, PRec):
        if not isinstance(v, dict): return None
        bindings = {}
        for key, sub in pat.fields:
            if key not in v: return None
            if isinstance(sub, PLit):
                if not teanga_eq(sub.v, v[key]): return None
            elif isinstance(sub, PBind):
                bindings[sub.name] = v[key]
            else:
                return None
        return bindings
    return None


# ============================================================
# BUILT-INS
# ============================================================

def install_builtins(env: Env) -> None:
    def b_print(interp, args):
        print(*[show(a) for a in args])
        return None

    def b_len(interp, args):
        v = args[0]
        if isinstance(v, (list, str)): return float(len(v))
        if isinstance(v, dict):        return float(len(v))
        raise RuntimeError(f"length: cannot take length of {type_of(v)}")

    def b_range(interp, args):
        if len(args) == 1:
            return [float(i) for i in range(int(args[0]))]
        return [float(i) for i in range(int(args[0]), int(args[1]))]

    def b_map(interp, args):
        xs, f = args
        return [interp.apply(f, [x]) for x in xs]

    def b_filter(interp, args):
        xs, f = args
        return [x for x in xs if truthy(interp.apply(f, [x]))]

    def b_fold(interp, args):
        xs, init, f = args
        acc = init
        for x in xs:
            acc = interp.apply(f, [acc, x])
        return acc

    def b_forEach(interp, args):
        xs, f = args
        for x in xs:
            interp.apply(f, [x])
        return None

    def b_typeof(interp, args):
        return type_of(args[0])

    def b_keys(interp, args):
        v = args[0]
        if not isinstance(v, dict):
            raise RuntimeError(f"keys: not an object: {type_of(v)}")
        return list(v.keys())

    def b_show(interp, args):
        return show(args[0])

    def b_readLine(interp, args):
        try: return input()
        except EOFError: return None

    env.set("print",   b_print)
    env.set("length",  b_len)
    env.set("range",   b_range)
    env.set("map",     b_map)
    env.set("filter",  b_filter)
    env.set("fold",    b_fold)
    env.set("forEach", b_forEach)
    env.set("typeof",  b_typeof)
    env.set("keys",    b_keys)
    env.set("show",    b_show)
    env.set("readLine",b_readLine)


# ============================================================
# DRIVER
# ============================================================

def run_file(path: str) -> Any:
    with open(path) as f:
        src = f.read()
    return run_source(src)


def run_source(src: str) -> Any:
    toks = lex(src)
    program = Parser(toks).parse_program()
    return Interp().run(program)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: teanga.py <file.tng>", file=sys.stderr)
        return 2
    try:
        run_file(sys.argv[1])
        return 0
    except (SyntaxError, NameError, RuntimeError, TeangaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
