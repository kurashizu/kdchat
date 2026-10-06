"""Mozilla's Bergamot translation engine (bergamot-translator.wasm, Firefox Translations) on the wasmtime runtime.

The .wasm is an Emscripten build made for a JavaScript host: its JS glue (bergamot-translator.js) provides the
runtime (heap growth, clock, sentence splitting via Intl.Segmenter) and embind, the C++ <-> JS bindings. This module
is that host in Python, cut down to what kdchat uses:

    b = Bergamot(wasm_bytes)
    m = b.model("de", "en", config_yaml, model, lex, [vocab])     # bytes of the model files
    b.translate(m, "Guten Morgen")                                # or b.translate(m1, "...", via=m2): pivoting
    b.free_model(m)

embind registers the C++ classes while the module's constructors run (_embind_register_* imports); a call goes
through the registered "invoker" (a function in the wasm table) with the arguments in embind's wire format:
integers as they are, std::string as a malloc'ed (u32 length, bytes) block, classes as pointers, shared_ptr as a
pointer to the smart pointer, value objects built with their registered constructor / field setters.
"""
from __future__ import annotations

import os
import re
import struct
import time

import wasmtime as W

_GEMM = {"int8_prepare_a": "int8PrepareAFallback", "int8_prepare_b": "int8PrepareBFallback",
         "int8_prepare_b_from_transposed": "int8PrepareBFromTransposedFallback",
         "int8_prepare_b_from_quantized_transposed": "int8PrepareBFromQuantizedTransposedFallback",
         "int8_prepare_bias": "int8PrepareBiasFallback", "int8_multiply_and_add_bias": "int8MultiplyAndAddBiasFallback",
         "int8_select_columns_of_b": "int8SelectColumnsOfBFallback"}
ENOSYS = 52                                          # (WASI errno)
_SENT_END = re.compile(r"(?<=[.!?。！？])[\"'”’）)\]]*\s+|(?<=[。！？])")


class EngineError(RuntimeError):
    pass


class _Abort(Exception):
    pass


def _sentences(text: str) -> list[str]:
    """split into sentences (what Intl.Segmenter does in the browser): after . ! ? (+ closing quotes) and a space, or
    after the full-width 。！？ ; the pieces keep their trailing spaces, so they add up to the text"""
    out, start = [], 0
    for m in _SENT_END.finditer(text):
        if m.end() > start and text[start:m.end()].strip():
            out.append(text[start:m.end()])
            start = m.end()
    if start < len(text) or not out:
        out.append(text[start:])
    return out


class Bergamot:
    def __init__(self, wasm: bytes, initial_memory: int = 16 << 20):
        self.engine = W.Engine()
        self.store = W.Store(self.engine)
        self.module = W.Module(self.engine, wasm)
        self.types: dict[int, tuple] = {}            # raw type id -> (kind, name, extra)
        self.classes: dict[str, dict] = {}           # class name -> {ctors: {argc: ...}, methods: {name: ...}, dtor}
        self.values: dict[int, dict] = {}            # value object type id -> {ctor, dtor, fields}
        self.smart: dict[int, dict] = {}             # shared_ptr type id -> {pointee, get, dtor}
        self.emvals: dict[int, list] = {}            # emval handle -> [type id, wire value, references]
        self._next_handle = 5                        # (embind reserves 0..4 for undefined / null / true / false)
        imports = []
        for imp in self.module.imports:
            t = imp.type
            if isinstance(t, W.MemoryType):
                self.mem = W.Memory(self.store, t)
                imports.append(self.mem)
                continue
            imports.append(W.Func(self.store, t, self._host(imp.module, imp.name, t)))
        self.inst = W.Instance(self.store, self.module, imports)
        self.ex = self.inst.exports(self.store)
        self.table = self.ex["__indirect_function_table"]
        self._malloc, self._free = self.ex["malloc"], self.ex["free"]
        self._grow_to(initial_memory)
        self._call(self.ex["__wasm_call_ctors"])
        self._service_sp = self._construct("BlockingService", [{"cacheSize": 0}])      # a shared_ptr
        self.service = self._pointee("BlockingService", self._service_sp)              # (methods take the raw one)

    # ------------------------------------------------------------------ memory
    def _grow_to(self, size: int) -> bool:
        cur = self.mem.data_len(self.store)
        if size <= cur:
            return True
        pages = (size - cur + 65535) // 65536
        try:
            self.mem.grow(self.store, pages)
            return True
        except Exception:                     # noqa: BLE001  (the maximum)
            return False

    def _read(self, p: int, n: int) -> bytes:
        return bytes(self.mem.read(self.store, p, p + n))

    def _write(self, p: int, data: bytes):
        self.mem.write(self.store, data, p)

    def _u32(self, p: int) -> int:
        return struct.unpack("<I", self._read(p, 4))[0]

    def _cstr(self, p: int) -> str:
        out = bytearray()
        while True:
            b = self._read(p, 256)
            i = b.find(b"\0")
            if i >= 0:
                return (out + b[:i]).decode("utf-8", "replace")
            out += b
            p += 256

    def malloc(self, n: int) -> int:
        p = self._call(self._malloc, n)
        if not p:
            raise EngineError(f"out of memory ({n} bytes)")
        return p

    def free(self, p: int):
        if p:
            self._call(self._free, p)

    def _call(self, f, *args):
        try:
            return f(self.store, *args)
        except _Abort as e:
            raise EngineError(str(e)) from None
        except W.WasmtimeError as e:          # a trap / an abort raised by a host function inside
            cause = e.__cause__ or e.__context__
            raise EngineError(str(cause) if isinstance(cause, _Abort) else f"engine trap: {e}") from None

    def _fn(self, idx: int):
        f = self.table.get(self.store, idx)
        if f is None:
            raise EngineError(f"no function {idx} in the table")
        return f

    # ------------------------------------------------------------------ host functions (the JS glue's job)
    def _host(self, module: str, name: str, ftype: W.FuncType):
        res = list(ftype.results)
        f64 = bool(res) and str(res[0]) == "f64"
        if module == "wasm_gemm":                   # int8 GEMM: the module's own portable implementation
            target = _GEMM[name]
            return lambda *a: self.ex[target](self.store, *a)
        if name.startswith("_embind_register_") or name == "_embind_finalize_value_object":
            h = getattr(self, "_reg_" + name[len("_embind_register_"):], None) if name != "_embind_finalize_value_object" \
                else (lambda t: None)
            return (lambda *a: (h(*a), None)[1]) if h else (lambda *a: None)
        table = {
            "emscripten_memcpy_big": lambda d, s, n: self._write(d, self._read(s, n)),
            "emscripten_resize_heap": lambda size: int(self._grow_to(size)),
            "emscripten_get_heap_max": lambda: 2 ** 31,
            "_emscripten_date_now": lambda: time.time() * 1000.0,
            "emscripten_get_now": lambda: time.perf_counter() * 1000.0,
            "_emscripten_get_now_is_monotonic": lambda: 1,
            "emscripten_asm_const_int": self._asm_const,
            "_emval_take_value": self._emval_take,
            "_emval_incref": self._emval_incref,
            "_emval_decref": self._emval_decref,
            "_emval_call": self._unsupported(name),
            "getentropy": lambda p, n: (self._write(p, os.urandom(n)), 0)[1],
            "environ_sizes_get": lambda pc, ps: (self._write(pc, b"\0" * 4), self._write(ps, b"\0" * 4), 0)[2],
            "environ_get": lambda a, b: 0,
            "fd_write": self._fd_write,
            "fd_close": lambda fd: 0,
            "fd_read": lambda *a: ENOSYS,
            "fd_seek": lambda *a: ENOSYS,
            "_localtime_js": lambda t, p: self._write(p, b"\0" * 44),
            "_tzset_js": lambda *a: None,
            "strftime_l": lambda s, maxsize, fmt, tm, loc: (self._write(s, b"\0"), 0)[1],
            "_mmap_js": lambda *a: -ENOSYS,
            "_munmap_js": lambda *a: -ENOSYS,
            "setTempRet0": lambda v: None,
            "pclose": lambda *a: -1,
            "abort": self._abort("abort"),
            "exit": self._abort("exit"),
            "__assert_fail": lambda c, f, l, fn: self._raise(f"assertion failed: {self._cstr(c)} at {self._cstr(f)}:{l}"),
            "__cxa_throw": self._abort("C++ exception"),
            "__cxa_rethrow": self._abort("C++ exception"),
            "__cxa_allocate_exception": lambda n: self.malloc(n),
        }
        if name in table:
            fn = table[name]
        elif name.startswith("__syscall_"):         # no file system: the models come from memory
            fn = lambda *a: -ENOSYS
        else:
            fn = self._unsupported(name)

        def call(*a):
            r = fn(*a)
            if res:
                r = 0 if r is None else r
                return float(r) if f64 else int(r)
            return None
        return call

    @staticmethod
    def _raise(msg):
        raise _Abort(msg)

    def _abort(self, what):
        def f(*a):
            raise _Abort(f"engine {what}")
        return f

    def _unsupported(self, name):
        def f(*a):
            raise _Abort(f"engine needs {name} (not provided)")
        return f

    def _fd_write(self, fd, iov, iovcnt, pnum):
        n = 0
        for i in range(iovcnt):
            n += self._u32(iov + 8 * i + 4)
        self._write(pnum, struct.pack("<I", n))
        return 0

    def _asm_const(self, code, sig, argbuf):
        """the one EM_ASM block: split a text into sentences (the browser uses Intl.Segmenter); args: text, lang,
        &count, &starts, &ends (UTF-8 byte offsets, malloc'ed arrays of i32)"""
        args = struct.unpack("<5I", self._read(argbuf, 20))       # (all i32: 4 bytes each, aligned)
        text = self._cstr(args[0])
        parts = _sentences(text)
        starts, ends, pos = [], [], 0
        for s in parts:
            starts.append(pos)
            pos += len(s.encode("utf-8"))
            ends.append(pos)
        n = len(parts)
        ps, pe = self.malloc(4 * n), self.malloc(4 * n)
        self._write(ps, struct.pack(f"<{n}i", *starts))
        self._write(pe, struct.pack(f"<{n}i", *ends))
        self._write(args[2], struct.pack("<i", n))
        self._write(args[3], struct.pack("<I", ps))
        self._write(args[4], struct.pack("<I", pe))
        return 0

    def _emval_take(self, tid, argv):
        kind = self.types.get(tid, ("?",))[0]
        if kind == "memory_view":
            v = struct.unpack("<II", self._read(argv, 8))      # (size, data pointer)
        else:
            v = self._u32(argv)                                 # a class: pointer to a new heap copy
        h = self._next_handle
        self._next_handle += 1
        self.emvals[h] = [tid, v, 1]
        return h

    def _emval_incref(self, h):
        if h in self.emvals:
            self.emvals[h][2] += 1

    def _emval_decref(self, h):
        e = self.emvals.get(h)
        if e is not None:
            e[2] -= 1
            if e[2] <= 0:
                del self.emvals[h]

    # ------------------------------------------------------------------ embind registration
    def _reg_void(self, t, name): self.types[t] = ("void", self._cstr(name))
    def _reg_bool(self, t, name, *a): self.types[t] = ("bool", self._cstr(name))
    def _reg_integer(self, t, name, *a): self.types[t] = ("int", self._cstr(name))
    def _reg_bigint(self, t, name, *a): self.types[t] = ("int", self._cstr(name))
    def _reg_float(self, t, name, *a): self.types[t] = ("float", self._cstr(name))
    def _reg_std_string(self, t, name): self.types[t] = ("string", self._cstr(name))
    def _reg_std_wstring(self, t, size, name): self.types[t] = ("wstring", self._cstr(name))
    def _reg_emval(self, t, name): self.types[t] = ("val", self._cstr(name))
    def _reg_memory_view(self, t, idx, name): self.types[t] = ("memory_view", self._cstr(name))

    def _reg_class(self, t, tp, tcp, base, gas, ga, us, u, ds, d, name, dsig, dtor):
        n = self._cstr(name)
        for tt in (t, tp, tcp):
            self.types[tt] = ("class", n)
        self.classes[n] = {"ctors": {}, "methods": {}, "dtor": dtor}

    def _class_of(self, t):
        return self.types[t][1]

    def _reg_class_constructor(self, cls, argc, args, sig, invoker, ctor):
        tids = [self._u32(args + 4 * i) for i in range(argc)]
        self.classes[self._class_of(cls)]["ctors"][argc - 1] = (tids, invoker, ctor)

    def _reg_class_function(self, cls, name, argc, args, sig, invoker, ctx, pure):
        tids = [self._u32(args + 4 * i) for i in range(argc)]
        self.classes[self._class_of(cls)]["methods"][self._cstr(name)] = (tids, invoker, ctx)

    def _reg_value_object(self, t, name, csig, ctor, dsig, dtor):
        self.types[t] = ("value", self._cstr(name))
        self.values[t] = {"ctor": ctor, "dtor": dtor, "fields": {}}

    def _reg_value_object_field(self, t, name, gt, gsig, getter, gctx, st, ssig, setter, sctx):
        self.values[t]["fields"][self._cstr(name)] = (st, setter, sctx)

    def _reg_smart_ptr(self, t, pointee, name, policy, gsig, get, csig, ctor, ssig, share, dsig, dtor):
        self.types[t] = ("smart", self._cstr(name))
        self.smart[t] = {"get": get, "dtor": dtor}

    # ------------------------------------------------------------------ calls
    def _to_wire(self, tid, v, cleanup: list):
        kind = self.types[tid][0]
        if kind in ("int", "bool"):
            return int(v)
        if kind == "string":
            b = v.encode("utf-8")
            p = self.malloc(4 + len(b) + 1)
            self._write(p, struct.pack("<I", len(b)) + b + b"\0")
            cleanup.append(lambda: self.free(p))
            return p
        if kind == "value":
            vo = self.values[tid]
            p = self._call(self._fn(vo["ctor"]))
            for k, (ft, setter, sctx) in vo["fields"].items():
                self._call(self._fn(setter), sctx, p, self._to_wire(ft, v[k], cleanup))
            cleanup.append(lambda: self._call(self._fn(vo["dtor"]), p))
            return p
        if kind in ("class", "smart"):
            return 0 if v is None else int(v)
        raise EngineError(f"cannot pass {self.types[tid]}")

    def _from_wire(self, tid, w):
        kind = self.types[tid][0]
        if kind == "void":
            return None
        if kind == "string":
            n = self._u32(w)
            s = self._read(w + 4, n).decode("utf-8", "replace")
            self.free(w)
            return s
        if kind == "val":                           # (the returned reference is ours: drop it)
            e = self.emvals.get(w)
            if e is None:
                return None
            self._emval_decref(w)
            return e[1]
        return w

    def _construct(self, cls, args):
        tids, invoker, ctor = self.classes[cls]["ctors"][len(args)]
        cleanup = []
        try:
            wires = [self._to_wire(t, a, cleanup) for t, a in zip(tids[1:], args)]
            return self._call(self._fn(invoker), ctor, *wires)
        finally:
            for c in reversed(cleanup):
                c()

    def _method(self, cls, name, this, *args):
        tids, invoker, ctx = self.classes[cls]["methods"][name]
        cleanup = []
        try:
            wires = [self._to_wire(t, a, cleanup) for t, a in zip(tids[2:], args)]
            r = self._call(self._fn(invoker), ctx, this, *wires)
            return self._from_wire(tids[0], r)
        finally:
            for c in reversed(cleanup):
                c()

    def _delete(self, cls, p):
        if p:
            self._call(self._fn(self.classes[cls]["dtor"]), p)

    def _pointee(self, cls, sp):
        for t, s in self.smart.items():
            if self.types[t][1] == cls:
                return self._call(self._fn(s["get"]), sp)
        raise EngineError(f"no smart pointer type for {cls}")

    def _delete_smart(self, cls, sp):
        for t, s in self.smart.items():
            if self.types[t][1] == cls:
                self._call(self._fn(s["dtor"]), sp)
                return

    # ------------------------------------------------------------------ the API kdchat uses
    def _aligned(self, data: bytes, align: int) -> int:
        m = self._construct("AlignedMemory", [len(data), align])
        size, ptr = self._method("AlignedMemory", "getByteArrayView", m)
        assert size == len(data), (size, len(data))
        self._write(ptr, data)
        return m

    def model(self, src: str, tgt: str, config: str, model: bytes, lex: bytes | None, vocabs: list[bytes],
              align: dict) -> int:
        """-> a TranslationModel (a shared_ptr); the engine keeps its own references to the memory blocks"""
        lst = self._construct("AlignedMemoryList", [])
        names = ["vocab"] if len(vocabs) == 1 else ["srcvocab", "trgvocab"]
        for data, kind in zip(vocabs, names):
            self._method("AlignedMemoryList", "push_back", lst, self._aligned(data, align[kind]))
        m = self._aligned(model, align["model"])
        lx = self._aligned(lex, align["lex"]) if lex else None
        try:
            return self._construct("TranslationModel", [src, tgt, config, m, lx, lst, None])
        finally:
            self._delete("AlignedMemoryList", lst)

    def free_model(self, m: int):
        self._delete_smart("TranslationModel", m)

    def translate(self, model: int, text: str, via: int | None = None) -> str:
        msgs = self._construct("VectorString", [])
        opts = self._construct("VectorResponseOptions", [])
        try:
            self._method("VectorString", "push_back", msgs, text)
            self._method("VectorResponseOptions", "push_back", opts, {"qualityScores": False, "alignment": False, "html": False})
            if via is None:
                r = self._method("BlockingService", "translate", self.service, model, msgs, opts)
            else:
                r = self._method("BlockingService", "translateViaPivoting", self.service, model, via, msgs, opts)
            try:
                resp = self._method("VectorResponse", "get", r, 0)
                try:
                    return self._method("Response", "getTranslatedText", resp)
                finally:
                    self._delete("Response", resp)
            finally:
                self._delete("VectorResponse", r)
        finally:
            self._delete("VectorString", msgs)
            self._delete("VectorResponseOptions", opts)
