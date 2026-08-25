"""In-memory Redis with a small Lua interpreter for tests.

The interpreter covers the exact Lua subset used by the production scripts in
``open_claude.execution_lease`` and ``open_claude.execution_coordinator`` so
tests exercise the same storage structures (strings, hashes, lists with TTL)
and the same branches as a real Redis server.  Tests never parse JSON to fake
the lease protocol.
"""
from __future__ import annotations

import fnmatch
import re
import threading
import time
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Minimal Lua tokenizer / parser / evaluator
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>--[^\n]*)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\.|==|~=|<=|>=|[.\-+*/<>=()\[\]{},])
    """,
    re.VERBOSE,
)

_KEYWORDS = {"local", "if", "then", "elseif", "else", "end",
             "while", "do", "return", "not", "and", "or",
             "nil", "true", "false"}


def _tokenize(script: str):
    pos = 0
    line = 1
    tokens = []
    while pos < len(script):
        match = _TOKEN_RE.match(script, pos)
        if not match:
            raise ValueError(f"Lua tokenize error near line {line}: {script[pos:pos+20]!r}")
        kind = match.lastgroup
        value = match.group()
        if kind == "ws":
            line += value.count("\n")
        elif kind == "comment":
            line += value.count("\n")
        elif kind == "number":
            tokens.append(_Token("number", value, line))
        elif kind == "string":
            tokens.append(_Token("string", _unquote(value), line))
        elif kind == "name":
            if value in _KEYWORDS:
                tokens.append(_Token(value, value, line))
            else:
                tokens.append(_Token("name", value, line))
        elif kind == "op":
            tokens.append(_Token("op", value, line))
        else:  # pragma: no cover - unreachable
            raise AssertionError(kind)
        pos = match.end()
    tokens.append(_Token("eof", "", line))
    return tokens


def _unquote(raw: str) -> str:
    body = raw[1:-1]
    return re.sub(r"\\(.)", r"\1", body)


class _Token:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind: str, value: Any, line: int):
        self.kind = kind
        self.value = value
        self.line = line


class _Nil:
    __slots__ = ()

    def __repr__(self):  # pragma: no cover
        return "nil"


NIL = _Nil()


class _LuaParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> _Token:
        return self.tokens[self.pos]

    def next(self) -> _Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, kind: str) -> _Token:
        token = self.next()
        if token.kind != kind:
            raise ValueError(
                f"Lua parse error line {token.line}: expected {kind}, got {token.kind} ({token.value!r})")
        return token

    # -- statements ----------------------------------------------------------

    def parse(self):
        statements = []
        while self.peek().kind != "eof":
            statements.append(self.statement())
        return statements

    def statement(self):
        token = self.peek()
        if token.kind == "name" and self.tokens[self.pos + 1].kind == "op" \
                and self.tokens[self.pos + 1].value == "=":
            self.next()  # name
            name = token.value
            self.next()  # "="
            value = self.expr()
            return ("assign", name, value)
        if token.kind == "local":
            self.next()
            name = self.expect("name").value
            if self.peek().kind == "op" and self.peek().value == "=":
                self.next()
                value = self.expr()
            else:
                value = None
            return ("local", name, value)
        if token.kind == "if":
            self.next()
            condition = self.expr()
            self.expect("then")
            body = self.block_until({"elseif", "else", "end"})
            clauses = [(condition, body)]
            while self.peek().kind == "elseif":
                self.next()
                cond = self.expr()
                self.expect("then")
                clauses.append((cond, self.block_until({"elseif", "else", "end"})))
            else_body = None
            if self.peek().kind == "else":
                self.next()
                else_body = self.block_until({"end"})
            self.expect("end")
            return ("if", clauses, else_body)
        if token.kind == "while":
            self.next()
            condition = self.expr()
            self.expect("do")
            body = self.block_until({"end"})
            self.expect("end")
            return ("while", condition, body)
        if token.kind == "return":
            self.next()
            values = []
            if self.peek().kind != "eof":
                values.append(self.expr())
                while self.peek().kind == "op" and self.peek().value == ",":
                    self.next()
                    values.append(self.expr())
            return ("return", values)
        return ("expr", self.expr())

    def block_until(self, kinds):
        body = []
        while self.peek().kind not in kinds | {"eof"}:
            body.append(self.statement())
        return body

    # -- expressions ----------------------------------------------------------

    def expr(self):
        return self.or_expr()

    def or_expr(self):
        node = self.and_expr()
        while self.peek().kind == "or":
            self.next()
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.cmp_expr()
        while self.peek().kind == "and":
            self.next()
            node = ("and", node, self.cmp_expr())
        return node

    def cmp_expr(self):
        node = self.concat_expr()
        token = self.peek()
        if token.kind == "op" and token.value in {"==", "~=", "<", "<=", ">", ">="}:
            self.next()
            node = (token.value, node, self.concat_expr())
        return node

    def concat_expr(self):
        node = self.add_expr()
        while self.peek().kind == "op" and self.peek().value == "..":
            self.next()
            node = ("concat", node, self.add_expr())
        return node

    def add_expr(self):
        node = self.mul_expr()
        while self.peek().kind == "op" and self.peek().value in {"+", "-"}:
            op = self.next().value
            node = (op, node, self.mul_expr())
        return node

    def mul_expr(self):
        node = self.unary()
        while self.peek().kind == "op" and self.peek().value in {"*", "/"}:
            op = self.next().value
            node = (op, node, self.unary())
        return node

    def unary(self):
        token = self.peek()
        if token.kind == "not":
            self.next()
            return ("not", self.unary())
        if token.kind == "op" and token.value == "-":
            self.next()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        token = self.next()
        if token.kind == "number":
            return ("num", float(token.value) if "." in token.value else int(token.value))
        if token.kind == "string":
            return ("str", token.value)
        if token.kind == "nil":
            return ("nil",)
        if token.kind == "true":
            return ("bool", True)
        if token.kind == "false":
            return ("bool", False)
        if token.kind == "name":
            if token.value == "redis":
                if self.peek().kind == "op" and self.peek().value == ".":
                    self.next()
                    self.expect("name")  # call
                return self.call_expr()
            if token.value in {"tonumber", "tostring", "type", "math.floor"}:
                return ("fncall", token.value, self.call_args())
            node = ("name", token.value)
            while self.peek().kind == "op" and self.peek().value == "[":
                self.next()
                index = self.expr()
                self.expect("op")  # "]"
                node = ("index", node, index)
            return node
        if token.kind == "op" and token.value == "(":
            node = self.expr()
            self.expect("op")
            return node
        if token.kind == "op" and token.value == "{":
            values = []
            if self.peek().kind == "op" and self.peek().value == "}":
                self.next()
                return ("table", values)
            values.append(self.expr())
            while self.peek().kind == "op" and self.peek().value == ",":
                self.next()
                if self.peek().kind == "op" and self.peek().value == "}":
                    break
                values.append(self.expr())
            self.expect("op")
            return ("table", values)
        raise ValueError(f"Lua parse error line {token.line}: unexpected {token.kind} {token.value!r}")

    def call_expr(self):
        return ("call", self.call_args())

    def call_args(self):
        self.expect("op")  # "("
        args = []
        if not (self.peek().kind == "op" and self.peek().value == ")"):
            args.append(self.expr())
            while self.peek().kind == "op" and self.peek().value == ",":
                self.next()
                args.append(self.expr())
        self.expect("op")  # ")"
        return args


def _truthy(value: Any) -> bool:
    return value is not NIL and value is not False


class _LuaEvaluator:
    def __init__(self, redis: "FakeRedis"):
        self.redis = redis

    def run(self, script: str, keys, argv):
        tokens = _tokenize(script)
        statements = _LuaParser(tokens).parse()
        env = {"KEYS": list(keys), "ARGV": list(argv)}
        try:
            for statement in statements:
                result = self.exec(statement, env)
                if statement[0] == "return":
                    return result
        except _ReturnSignal as signal:
            return signal.value
        return NIL

    def exec(self, node, env):
        kind = node[0]
        if kind == "local":
            _, name, value_node = node
            value = self.exec(value_node, env) if value_node is not None else NIL
            env[name] = value
            return NIL
        if kind == "assign":
            _, name, value_node = node
            env[name] = self.exec(value_node, env)
            return NIL
        if kind == "if":
            _, clauses, else_body = node
            for condition, body in clauses:
                if _truthy(self.exec(condition, env)):
                    self.run_block(body, env)
                    return NIL
            if else_body is not None:
                self.run_block(else_body, env)
            return NIL
        if kind == "while":
            _, condition, body = node
            while _truthy(self.exec(condition, env)):
                self.run_block(body, env)
            return NIL
        if kind == "return":
            values = [self.exec(item, env) for item in node[1]]
            if len(values) == 1:
                return values[0]
            return values
        if kind == "expr":
            return self.exec(node[1], env)
        # expressions
        if kind == "num":
            return node[1]
        if kind == "str":
            return node[1]
        if kind == "nil":
            return NIL
        if kind == "bool":
            return node[1]
        if kind == "name":
            if node[1] == "KEYS" or node[1] == "ARGV":
                return env[node[1]]
            return env.get(node[1], NIL)
        if kind == "index":
            table_value = self.exec(node[1], env)
            index = self.exec(node[2], env)
            if table_value is NIL or index is NIL:
                return NIL
            if isinstance(table_value, list):
                try:
                    if isinstance(index, float) and index.is_integer():
                        index = int(index)
                    return table_value[int(index) - 1] if int(index) >= 1 else NIL
                except (IndexError, TypeError, ValueError):
                    return NIL
            if isinstance(table_value, dict):
                return table_value.get(str(index), NIL)
            return NIL
        if kind == "call":
            args = [self.exec(arg, env) for arg in node[1]]
            return self.redis.lua_call(*args)
        if kind == "fncall":
            name, args = node[1], [self.exec(arg, env) for arg in node[2]]
            if name == "tonumber":
                if len(args) != 1 or args[0] is NIL:
                    return NIL
                try:
                    return float(args[0]) if isinstance(args[0], float) else (
                        int(float(args[0])) if str(args[0]).strip() else NIL)
                except (TypeError, ValueError):
                    return NIL
            if name == "tostring":
                return "nil" if args[0] is NIL else str(args[0])
            if name == "type":
                if args[0] is NIL:
                    return "nil"
                if isinstance(args[0], list):
                    return "table"
                return "string" if isinstance(args[0], str) else "number"
            if name == "math.floor":
                return NIL if args[0] is NIL else int(float(args[0]))
            return NIL
        if kind == "table":
            return [self.exec(item, env) for item in node[1]]
        if kind in {"or", "and"}:
            _, left, right = node
            if kind == "or":
                left_value = self.exec(left, env)
                return left_value if _truthy(left_value) else self.exec(right, env)
            left_value = self.exec(left, env)
            return self.exec(right, env) if _truthy(left_value) else left_value
        if kind == "not":
            return not _truthy(self.exec(node[1], env))
        if kind == "neg":
            return -self.exec(node[1], env)
        if kind in {"+", "-", "*", "/"}:
            left = self.exec(node[1], env)
            right = self.exec(node[2], env)
            if left is NIL or right is NIL:
                return NIL
            # Lua coerces numeric strings in arithmetic ("1" + 2 == 3.0);
            # the production scripts rely on this for ARGV timestamps.
            if isinstance(left, str):
                try:
                    left = float(left)
                except ValueError:
                    pass
            if isinstance(right, str):
                try:
                    right = float(right)
                except ValueError:
                    pass
            if kind == "+":
                return left + right
            if kind == "-":
                return left - right
            if kind == "*":
                return left * right
            return left / right
        if kind == "concat":
            left = self.exec(node[1], env)
            right = self.exec(node[2], env)
            if left is NIL or right is NIL:
                return NIL
            return str(left) + str(right)
        if kind in {"==", "~=", "<", "<=", ">", ">="}:
            left = self.exec(node[1], env)
            right = self.exec(node[2], env)
            if kind == "==":
                return left == right
            if kind == "~=":
                return left != right
            if kind == "<":
                return left < right
            if kind == "<=":
                return left <= right
            if kind == ">":
                return left > right
            return left >= right
        raise ValueError(f"unsupported Lua node {kind!r}")

    def run_block(self, statements, env):
        for statement in statements:
            if statement[0] == "return":
                raise _ReturnSignal(self.exec(statement, env))
            self.exec(statement, env)


class _ReturnSignal(Exception):
    def __init__(self, value):
        super().__init__()
        self.value = value


# ---------------------------------------------------------------------------
# FakeRedis
# ---------------------------------------------------------------------------


class _StringItem:
    __slots__ = ("value", "expires")

    def __init__(self, value, expires=None):
        self.value = value
        self.expires = expires


class _HashItem:
    __slots__ = ("fields", "expires")

    def __init__(self, fields, expires=None):
        self.fields = dict(fields)
        self.expires = expires


class _ListItem:
    __slots__ = ("values", "expires")

    def __init__(self, values, expires=None):
        self.values = list(values)
        self.expires = expires


class FakeRedis:
    """In-memory Redis honoring TTLs plus the Lua subset used by the servers.

    ``eval`` is serialized with a lock, mirroring real Redis where each Lua
    script runs atomically: two concurrent instances can therefore never
    double-decrement counters or double-recover the same execution.
    """

    def __init__(self, clock: Optional[Callable[[], float]] = None):
        self._clock = clock or time.time
        self._data: dict[str, Any] = {}
        self._interpreter = _LuaEvaluator(self)
        self._lua_lock = threading.Lock()

    # -- helpers ---------------------------------------------------------------

    def _purge(self, key: str) -> None:
        item = self._data.get(key)
        if item is None:
            return
        if item.expires is not None and self._clock() >= item.expires:
            del self._data[key]

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def lua_call(self, command: str, *args) -> Any:
        """Execute a ``redis.call(...)`` from inside a Lua script."""
        method = getattr(self, f"_lua_{command}", None)
        if method is None:
            raise ValueError(f"unsupported redis.call in Lua: {command}")
        return method(*args)

    def _lua_exists(self, *keys) -> int:
        count = 0
        for key in keys:
            self._purge(key)
            if key in self._data:
                count += 1
        return count

    def _lua_set(self, key, value, *options) -> str:
        expires = None
        for index in range(0, len(options), 2):
            if options[index] == "PX":
                expires = self._clock() + int(options[index + 1]) / 1000.0
        self._purge(key)
        self._data[key] = _StringItem(str(value), expires)
        return "OK"

    def _lua_get(self, key):
        self._purge(key)
        item = self._data.get(key)
        if item is None:
            return NIL
        return item.value

    def _lua_del(self, *keys) -> int:
        count = 0
        for key in keys:
            self._purge(key)
            if key in self._data:
                del self._data[key]
                count += 1
        return count

    def _lua_hset(self, key, *pairs) -> int:
        self._purge(key)
        item = self._data.get(key)
        if item is None:
            item = _HashItem({})
            self._data[key] = item
        added = 0
        for index in range(0, len(pairs), 2):
            field = str(pairs[index])
            value = str(pairs[index + 1])
            if field not in item.fields:
                added += 1
            item.fields[field] = value
        return added

    def _lua_hget(self, key, field):
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _HashItem):
            return NIL
        return item.fields.get(str(field), NIL)

    def _lua_hgetall(self, key):
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _HashItem):
            return []
        result = []
        for field, value in item.fields.items():
            result.extend([field, value])
        return result

    def _lua_pexpire(self, key, ms) -> int:
        self._purge(key)
        item = self._data.get(key)
        if item is None:
            return 0
        item.expires = self._clock() + int(ms) / 1000.0
        return 1

    def _lua_incr(self, key) -> int:
        self._purge(key)
        item = self._data.get(key)
        if item is None:
            item = _StringItem("0")
            self._data[key] = item
        elif not isinstance(item, _StringItem):
            raise ValueError("WRONGTYPE")
        value = int(item.value) + 1
        item.value = str(value)
        return value

    def _lua_rpush(self, key, *values) -> int:
        self._purge(key)
        item = self._data.get(key)
        if item is None:
            item = _ListItem([])
            self._data[key] = item
        elif not isinstance(item, _ListItem):
            raise ValueError("WRONGTYPE")
        item.values.extend(str(value) for value in values)
        return len(item.values)

    def _lua_lpop(self, key):
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _ListItem) or not item.values:
            return NIL
        return item.values.pop(0)

    def _lua_lrem(self, key, count, value) -> int:
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _ListItem):
            return 0
        wanted = str(value)
        removed = 0
        remaining = []
        count = int(count)
        if count >= 0:
            for current in item.values:
                if current == wanted and (count == 0 or removed < count):
                    removed += 1
                    continue
                remaining.append(current)
        else:
            for current in reversed(item.values):
                if current == wanted and removed < -count:
                    removed += 1
                    continue
                remaining.insert(0, current)
        item.values = remaining
        return removed

    def _lua_lindex(self, key, index) -> Any:
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _ListItem):
            return NIL
        index = int(index)
        if index < 0:
            index = len(item.values) + index
        if index < 0 or index >= len(item.values):
            return NIL
        return item.values[index]

    def _lua_llen(self, key) -> int:
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _ListItem):
            return 0
        return len(item.values)

    # -- client-facing commands -------------------------------------------------

    def ping(self):
        return True

    def exists(self, key) -> int:
        self._purge(key)
        return 1 if key in self._data else 0

    def set(self, key, value, nx=False, px=None):
        self._purge(key)
        if nx and key in self._data:
            return False
        expires = None
        if px is not None:
            expires = self._clock() + int(px) / 1000.0
        self._data[key] = _StringItem(str(value), expires)
        return True

    def get(self, key):
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _StringItem):
            return None
        return item.value

    def delete(self, *keys) -> int:
        return self._lua_del(*keys)

    def incr(self, key) -> int:
        return self._lua_incr(key)

    def hset(self, key, mapping=None, **fields):
        self._purge(key)
        item = self._data.get(key)
        if item is None:
            item = _HashItem({})
            self._data[key] = item
        elif not isinstance(item, _HashItem):
            raise ValueError("WRONGTYPE")
        added = 0
        pairs = dict(mapping or {})
        pairs.update(fields)
        for field, value in pairs.items():
            if field not in item.fields:
                added += 1
            item.fields[str(field)] = str(value)
        return added

    def hget(self, key, field):
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _HashItem):
            return None
        return item.fields.get(str(field))

    def hgetall(self, key):
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _HashItem):
            return {}
        return dict(item.fields)

    def pexpire(self, key, ms) -> int:
        return self._lua_pexpire(key, ms)

    def rpush(self, key, *values) -> int:
        return self._lua_rpush(key, *values)

    def lpop(self, key):
        return self._lua_lpop(key)

    def lrem(self, key, count, value) -> int:
        return self._lua_lrem(key, count, value)

    def lindex(self, key, index):
        return self._lua_lindex(key, index)

    def llen(self, key) -> int:
        return self._lua_llen(key)

    def lrange(self, key, start, end) -> list:
        self._purge(key)
        item = self._data.get(key)
        if item is None or not isinstance(item, _ListItem):
            return []
        values = item.values
        count = len(values)
        if start < 0:
            start = max(0, count + start)
        if end < 0:
            end = count + end
        end = min(count - 1, end)
        if start > end:
            return []
        return list(values[start:end + 1])

    def keys(self, pattern) -> list:
        return [key for key in list(self._data) if fnmatch.fnmatchcase(key, pattern)]

    def scan_iter(self, match=None, count=10):
        """SCAN-style iterator over live keys (pattern-filtered)."""
        seen = 0
        for key in list(self._data):
            if match is not None and not fnmatch.fnmatchcase(key, match):
                continue
            seen += 1
            if seen > count:
                return
            yield key

    def eval(self, script, numkeys, *args):
        """Run a Lua script with KEYS=args[:numkeys], ARGV=args[numkeys:]."""
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])
        with self._lua_lock:
            result = self._interpreter.run(script, keys, argv)
        if result is NIL:
            return None
        if isinstance(result, list):
            return [None if item is NIL else item for item in result]
        return result
