#!/usr/bin/env python3
"""head_cache.py — a HOST copy of the LM head, for VERIFICATION ONLY.

======================================================================
THIS IS NOT A DECODE PATH.
======================================================================
Model compute stays ON-CHIP (user ruling, 2026-08-11, which overrides
docs/SAMPLING_SPEC.md S1/S2).  The shipped decode step is a FULL
sequencer launch: the LM head and the argmax run on the FPGA exactly as
they do today, and the token still comes out of the SEQ OUT FIFO.
Sampling will consume an ON-CHIP top-k capture unit that arrives with the
next RTL rung; see sw/chat_seq.py:ChipTopKSource.

What this module is for, and nothing else:

  * `chat_seq.py --verify-head` — a continuous chip-vs-host cross-check.
    The host rebuilds the head's logits from the SAME int8 activation
    vector the chip used (read back out of the layer_chan scratchpad
    post-halt) and asserts that its argmax is the token the chip's AMAXL
    pushed.  Every disagreement is a hardware/quantisation bug caught.
  * the board-free sampler gate — the offline driver in chat_seq.py runs
    ref/seq_model.py for the hidden state and this module for the head,
    so the whole sampling path can be exercised with no board at all.
  * offline diagnostics: "what WOULD the top-32 have been at that step".

======================================================================
The arithmetic (docs/SAMPLING_SPEC.md S4, unchanged by the pivot)
======================================================================
One head row of the committed image is the v2 W4 row format
(ref/w4a8_ref.py module header): `wb = K//128` weight beats of nibble
packed int4, then `sb` scale beats of uint16 group mantissas.  The engine
computes, per row,

    p   = SUM_g m[g] * SUM_{k in g} w4[k] * x8[k]        (exact integers)
    y32 = rshift_round(p, sh)                            (round half away)

and the argmax/top-k units rank y32.  ref/w4a8_ref.py:matvec_y32 IS that
definition, so `exact_rows()` below simply calls it — there is no second
implementation of the chip's arithmetic in this file.

The dequantised logit of row r is

    logit = y32[r] * 2^(e + sh - 15 + e_x - RS_F)

with (e, sh) from the weight manifest, RS_F = ref/layer_fixed.RS_F = 8
the residual-stream fraction, and e_x = the DYNQ8 exponent of the
activation vector (layer_chan L_EOUT[3:0], 0..15, always >= 0).  For the
committed head (e=-4, sh=5) that is the spec's `y32 * 2^(e_x - 22)`.

The f32 dense copy holds `w4 * m` EXACTLY (max |w4*m| = 93,646 < 2^24),
so `Wf @ x8` differs from the integer p only by f32 accumulation
rounding: measured max relative error 2.86e-6 on the real head, 570x
smaller than the 49th-50th logit gap.  It is still an APPROXIMATION, so
every value this module hands back as "what the chip would have seen" is
RESCORED in exact integer arithmetic first (`topk()`, `argmax()`).

======================================================================
Cost (snoke, 48-core E5-2650 v4, numpy 2.4.6 / scipy-openblas 0.3.31)
======================================================================
  build f32 from the 143 MB DDR image      3.3 s   (1017 MB resident)
  write the local-disk cache               0.7 s
  load the cache (warm page cache)         0.4 s
  f32 GEMV, 248320x1024, 16 BLAS threads   17.9 ms  (57 GB/s, one NUMA node)
                     ... under numactl --interleave=all   10.3 ms  (99 GB/s)
  exact integer rescore of 40 rows         0.6 ms
  argmax = GEMV + rescore (--verify-head)  19.4 ms
  exact integer pass over the WHOLE head   5.8 s    (gate use only)

MEASURED, not assumed: the GEMV is memory-bound and saturates at 8 threads
(1/2/4/8/16/48 threads -> 79/41/29/18.1/17.9/18.0 ms), so S2's "pin 16"
costs nothing and the only lever that matters on this 2-socket box is
spreading the 1 GB over both memory controllers.

The cache goes on LOCAL disk (~/.cache/fable5_llm by default, /tmp as the
fallback).  NEVER on the NFS share: 1 GB per read over NFS would cost
more than rebuilding it.  `cache_dir()` refuses an NFS path and says so.
"""
import ctypes
import hashlib
import json
import os
import re
import sys
import time

import numpy as np

SW_DIR = os.path.dirname(os.path.abspath(__file__))
TOP_DIR = os.path.dirname(SW_DIR)
REF_DIR = os.path.join(TOP_DIR, "ref")
for _p in (SW_DIR, REF_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import w4a8_ref as W4                                          # noqa: E402
try:
    from layer_fixed import RS_F                               # noqa: E402
except Exception:                                              # pragma: no cover
    RS_F = 8                       # ref/layer_fixed.py:RS_F (residual Q7.8)

HEAD_WID = 186                     # the tied LM head in model_v2_s1
BUILDER_VERSION = 1                # bump when the f32 layout changes
DEFAULT_THREADS = 16               # docs/SAMPLING_SPEC.md S2
RESCORE_MARGIN = 8                 # S3: rescore top-(k+8), never top-k


class HeadCacheError(RuntimeError):
    pass


# ======================================================================
# BLAS thread control
# ======================================================================
def _blas_libs():
    """Every BLAS-looking shared object mapped into this process."""
    out = []
    try:
        with open("/proc/self/maps") as f:
            for ln in f:
                m = re.search(r"(\S*(?:openblas|blis|mkl_rt)\S*\.so[^\s]*)", ln)
                if m:
                    out.append(m.group(1))
    except OSError:                                            # pragma: no cover
        pass
    return sorted(set(out))


# scipy-openblas (what the numpy wheels vendor) renames every symbol with a
# `scipy_` prefix and an ILP64 `64_` suffix, so the plain OpenBLAS names are
# NOT exported.  Try all four spellings before giving up.
_SET_SYMS = ("openblas_set_num_threads64_", "openblas_set_num_threads",
             "scipy_openblas_set_num_threads64_",
             "scipy_openblas_set_num_threads_64_",
             "goto_set_num_threads64_", "goto_set_num_threads",
             "scipy_goto_set_num_threads64_")
_GET_SYMS = ("openblas_get_num_threads64_", "openblas_get_num_threads",
             "scipy_openblas_get_num_threads64_",
             "scipy_openblas_get_num_threads_64_")


def set_blas_threads(n=DEFAULT_THREADS):
    """Pin the BLAS thread pool to `n` AT RUNTIME.  Returns (n_set, how).

    OPENBLAS_NUM_THREADS is read when the library loads, and numpy loads it
    at `import numpy` — long before any caller of this module gets a say.
    So the env var alone cannot pin an already-running process; we call
    openblas_set_num_threads() through ctypes instead and set the env var
    too, for anything this process spawns later.
    """
    n = int(n)
    for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"):
        os.environ[k] = str(n)
    for path in _blas_libs():
        try:
            lib = ctypes.CDLL(path)
        except OSError:                                        # pragma: no cover
            continue
        for s in _SET_SYMS:
            fn = getattr(lib, s, None)
            if fn is None:
                continue
            fn.argtypes = [ctypes.c_int]
            fn.restype = None
            fn(n)
            got = None
            for g in _GET_SYMS:
                gf = getattr(lib, g, None)
                if gf is not None:
                    gf.restype = ctypes.c_int
                    got = int(gf())
                    break
            return (got if got is not None else n,
                    f"{s}() in {os.path.basename(path)}")
    return None, ("no openblas_set_num_threads symbol found in "
                  + (", ".join(os.path.basename(p) for p in _blas_libs())
                     or "any mapped library")
                  + " — the pool keeps whatever OPENBLAS_NUM_THREADS was at "
                    "import numpy")


# ======================================================================
# cache location
# ======================================================================
def _fstype(path):
    """Filesystem type of the mount `path` lives on ('' if unknown)."""
    try:
        with open("/proc/mounts") as f:
            mounts = [ln.split()[:3] for ln in f]
    except OSError:                                            # pragma: no cover
        return ""
    p = os.path.abspath(path)
    best, kind = "", ""
    for _dev, mp, ty in mounts:
        mp = mp.replace("\\040", " ")
        if (p == mp or p.startswith(mp.rstrip("/") + "/")) and len(mp) > len(best):
            best, kind = mp, ty
    return kind


def is_network_fs(path):
    return _fstype(path).startswith(("nfs", "cifs", "smb", "fuse.sshfs"))


def cache_dir(explicit=None, log=None):
    """A LOCAL-disk directory for the 1 GB f32 head (S2).

    Order: --head-cache / $FABLE5_HEAD_CACHE, then $XDG_CACHE_HOME or
    ~/.cache, then /tmp.  A network filesystem is refused at every step:
    re-reading 1 GB over NFS costs more than rebuilding from the image.
    """
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("FABLE5_HEAD_CACHE"):
        cands.append(os.environ["FABLE5_HEAD_CACHE"])
    xdg = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    cands.append(os.path.join(xdg, "fable5_llm"))
    cands.append(os.path.join("/tmp", "fable5_llm-%s"
                              % (os.environ.get("USER") or os.getuid())))
    for c in cands:
        c = os.path.abspath(os.path.expanduser(c))
        parent = c
        while parent != "/" and not os.path.isdir(parent):
            parent = os.path.dirname(parent)
        if is_network_fs(parent):
            if log:
                log(f"  head cache SKIPPING {c}: {_fstype(parent)} is a "
                    f"network filesystem (S2 says LOCAL disk)")
            continue
        try:
            os.makedirs(c, exist_ok=True)
        except OSError as e:                                   # pragma: no cover
            if log:
                log(f"  head cache SKIPPING {c}: {e}")
            continue
        return c
    raise HeadCacheError("no writable LOCAL cache directory (tried: %s)"
                         % ", ".join(cands))


# ======================================================================
# the head
# ======================================================================
class HeadSpec(object):
    """One weight-manifest entry, with the v2 row geometry resolved."""

    def __init__(self, wid, m, wdir):
        self.wid = int(wid)
        self.file = m["file"]
        self.path = os.path.join(wdir, m["file"])
        self.nrows = int(m["nrows"])
        self.k = int(m["k"])
        self.stride = int(m["stride"])
        self.sh = int(m["sh"])
        self.e = int(m["e"])
        self.ng = int(m["ng"])
        self.g = int(m.get("g", 128))
        self.wb, self.sb = W4.row_beats(self.k, self.g)
        if (self.wb + self.sb) * 64 != self.stride:
            raise HeadCacheError(
                f"wid {self.wid}: manifest stride {self.stride} != "
                f"({self.wb}+{self.sb})*64 from ref/w4a8_ref.row_beats")
        self.nscale = self.k // self.g

    @property
    def bytes(self):
        return self.nrows * self.stride

    def logit_exp(self, e_x):
        """log2 of the scale that turns y32 into a real logit (S4)."""
        return self.e + self.sh - 15 + int(e_x) - RS_F

    def logit_scale(self, e_x):
        return float(2.0 ** self.logit_exp(e_x))

    def as_dict(self):
        return {"wid": self.wid, "file": self.file, "nrows": self.nrows,
                "k": self.k, "stride": self.stride, "sh": self.sh,
                "e": self.e, "ng": self.ng, "g": self.g,
                "rs_f": RS_F, "logit_exp_at_ex0": self.logit_exp(0)}


def load_spec(prefix, wid=HEAD_WID):
    """(HeadSpec, manifest) for <prefix>.weights.json entry `wid`."""
    manf = prefix + ".weights.json"
    with open(manf) as f:
        man = json.load(f)
    if str(wid) not in man:
        raise HeadCacheError(f"{manf} has no wid {wid} (the LM head)")
    return HeadSpec(wid, man[str(wid)], os.path.dirname(os.path.abspath(prefix))
                    or "."), man


class HostHead(object):
    """VERIFICATION-ONLY f32 copy of the LM head + the exact integer path.

    `f32` is (nrows, k) float32 holding w4*m EXACTLY.  `p_f32(x8)` is a
    BLAS sgemv over it; every number that is claimed to be "the chip's" is
    recomputed by `exact_rows()` (ref/w4a8_ref.matvec_y32) before it is
    returned.
    """

    def __init__(self, spec, log=print):
        self.spec = spec
        self.log = log
        self.f32 = None
        self.src = None                 # memmap of the DDR image
        self.built_from = None
        self.build_s = None
        self.load_s = None
        self.threads = None
        self.thread_how = None

    # ------------------------------------------------------------ image
    def open_image(self):
        if self.src is None:
            s = self.spec
            n = os.path.getsize(s.path)
            if n != s.bytes:
                raise HeadCacheError(
                    f"{s.file} is {n} B, the manifest says "
                    f"{s.nrows}*{s.stride} = {s.bytes} B")
            self.src = np.memmap(s.path, dtype=np.uint8,
                                 mode="r").reshape(s.nrows, s.stride)
        return self.src

    def rows_w4_m(self, idx):
        """(w4 (n,K) int8, m (n,NG) uint16) for the given row indices."""
        s = self.spec
        img = self.open_image()
        idx = np.asarray(idx, dtype=np.int64)
        if idx.size and (idx.min() < 0 or idx.max() >= s.nrows):
            raise HeadCacheError(f"row index out of range 0..{s.nrows - 1}")
        blk = np.asarray(img[idx])                        # (n, stride) copy
        w4 = W4.unpack_w4(blk[:, :s.wb * 64], s.k)
        m = blk[:, s.wb * 64:s.wb * 64 + 2 * s.nscale].copy().view(np.uint16)
        return w4, m

    # ------------------------------------------------------------ build
    def build(self, verbose=True):
        """DDR image -> dense f32 (w4*m, exact in f32)."""
        s = self.spec
        img = self.open_image()
        t0 = time.perf_counter()
        out = np.empty((s.nrows, s.k), dtype=np.float32)
        CH = 16384
        for r0 in range(0, s.nrows, CH):
            r1 = min(s.nrows, r0 + CH)
            blk = np.asarray(img[r0:r1])
            m = blk[:, s.wb * 64:s.wb * 64 + 2 * s.nscale].copy().view(np.uint16)
            out[r0:r1] = (W4.unpack_w4(blk[:, :s.wb * 64], s.k).astype(np.float32)
                          * np.repeat(m.astype(np.float32), s.g, axis=1))
        self.f32 = out
        self.build_s = time.perf_counter() - t0
        self.built_from = "image"
        mx = float(np.abs(out).max())
        if mx >= 2.0 ** 24:
            raise HeadCacheError(
                f"max |w4*m| = {mx:.0f} >= 2^24: the f32 copy is no longer "
                f"exact, so the f32 prefilter cannot be trusted")
        if verbose:
            self.log(f"  head build {s.file} -> f32 {out.nbytes / 2**20:.0f} "
                     f"MiB in {self.build_s:.2f}s (max|w4*m| = {mx:.0f} < 2^24, "
                     f"exact in f32)")
        return out

    # ------------------------------------------------------------ cache
    def _sidecar(self, path):
        return path + ".json"

    def cache_path(self, cdir):
        s = self.spec
        key = f"{s.file}:{s.bytes}:{s.k}:{s.g}:{s.sh}:{s.e}:v{BUILDER_VERSION}"
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        return os.path.join(cdir, f"head_w{s.wid}_{h}_f32.bin")

    def probe_sha(self, blocks=(0.0, 0.5, 1.0), nb=1 << 16):
        """Cheap content fingerprint of the source image (~20 ms).

        The mtime of an NFS-hosted artifact is not reliable (observed
        flip-flopping between two values on this tree), and a
        requantisation can produce a byte-different image of exactly the
        same size.  So: mtime is advisory, this is the tiebreak, and a
        full sha256 of 143 MB is not paid on every session.
        """
        h = hashlib.sha256()
        size = os.path.getsize(self.spec.path)
        h.update(f"{size}:{nb}".encode())
        with open(self.spec.path, "rb") as f:
            for frac in blocks:
                off = min(max(0, int((size - nb) * frac)), max(0, size - nb))
                off -= off % self.spec.stride
                f.seek(off)
                h.update(f.read(nb))
        return h.hexdigest()

    def _meta(self, st):
        d = self.spec.as_dict()
        d.update({"builder_version": BUILDER_VERSION,
                  "src_bytes": st.st_size, "src_mtime_ns": st.st_mtime_ns,
                  "src_probe_sha256": self.probe_sha(),
                  "dtype": "float32", "shape": [self.spec.nrows, self.spec.k],
                  "not_a_decode_path": "verification only — the chip owns the "
                                       "LM head (user ruling 2026-08-11)"})
        return d

    def save_cache(self, path):
        st = os.stat(self.spec.path)
        t0 = time.perf_counter()
        tmp = path + ".tmp%d" % os.getpid()
        self.f32.tofile(tmp)
        os.replace(tmp, path)
        meta = self._meta(st)
        meta["written"] = time.time()
        with open(self._sidecar(path), "w") as f:
            json.dump(meta, f, indent=1)
        dt = time.perf_counter() - t0
        self.log(f"  head cache wrote {os.path.getsize(path) / 2**20:.0f} MiB "
                 f"-> {path} ({dt:.2f}s)")
        return dt

    def load_cache(self, path, mmap=False):
        """True if a VALID cache was loaded (size/mtime/geometry all match)."""
        side = self._sidecar(path)
        if not (os.path.exists(path) and os.path.exists(side)):
            return False
        try:
            with open(side) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            return False
        st = os.stat(self.spec.path)
        want = self._meta(st)
        for k in ("wid", "nrows", "k", "stride", "sh", "e", "g", "rs_f",
                  "builder_version", "src_bytes", "src_probe_sha256"):
            if meta.get(k) != want[k]:
                self.log(f"  head cache STALE ({k}: {meta.get(k)!r} != "
                         f"{want[k]!r}) — rebuilding")
                return False
        if meta.get("src_mtime_ns") != want["src_mtime_ns"]:
            self.log(f"  head cache mtime moved "
                     f"({meta.get('src_mtime_ns')} -> "
                     f"{want['src_mtime_ns']}) but the content fingerprint "
                     f"still matches — keeping the cache")
        want_bytes = self.spec.nrows * self.spec.k * 4
        if os.path.getsize(path) != want_bytes:
            self.log("  head cache STALE (size) — rebuilding")
            return False
        t0 = time.perf_counter()
        if mmap:
            self.f32 = np.memmap(path, dtype=np.float32, mode="r").reshape(
                self.spec.nrows, self.spec.k)
        else:
            self.f32 = np.fromfile(path, dtype=np.float32).reshape(
                self.spec.nrows, self.spec.k)
        self.load_s = time.perf_counter() - t0
        self.built_from = "cache" + ("(mmap)" if mmap else "")
        self.log(f"  head cache loaded {want_bytes / 2**20:.0f} MiB from "
                 f"{path} in {self.load_s:.2f}s"
                 + (" (mmap)" if mmap else ""))
        return True

    # ------------------------------------------------------------ maths
    def p_f32(self, x8):
        """Wf @ x8 — the APPROXIMATE (but 2.9e-6-tight) row products."""
        x = np.asarray(x8, dtype=np.float32)
        if x.shape != (self.spec.k,):
            raise HeadCacheError(f"x8 must be ({self.spec.k},), got {x.shape}")
        return self.f32 @ x

    def exact_rows(self, idx, x8):
        """(y32 int32, p int64) for `idx`, in the CHIP's exact arithmetic.

        This is ref/w4a8_ref.matvec_y32 itself — the same function the
        Verilator TBs compare the RTL against — restricted to the rows we
        actually care about.  No second implementation exists here.
        """
        s = self.spec
        idx = np.asarray(idx, dtype=np.int64)
        if idx.size == 0:
            return (np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.int64))
        w4, m = self.rows_w4_m(idx)
        x = np.asarray(x8, dtype=np.int8)
        y32 = W4.matvec_y32(w4, m, s.sh, x, g=s.g)
        acc = (w4.reshape(len(idx), s.nscale, s.g).astype(np.int64)
               * x.astype(np.int64).reshape(1, s.nscale, s.g)).sum(axis=2)
        p = (m.astype(np.int64) * acc).sum(axis=1)
        return y32, p

    def exact_all(self, x8, chunk=16384):
        """y32 for EVERY row, exactly.  ~4 s — gate use only, never per token."""
        s = self.spec
        out = np.empty(s.nrows, dtype=np.int32)
        for r0 in range(0, s.nrows, chunk):
            r1 = min(s.nrows, r0 + chunk)
            y, _p = self.exact_rows(np.arange(r0, r1), x8)
            out[r0:r1] = y
        return out

    def topk(self, x8, k, margin=RESCORE_MARGIN):
        """The chip-equivalent top-k: (values int32[k], indices int64[k]).

        f32 picks the top-(k+margin) candidates, exact integer arithmetic
        rescores THOSE rows, and the ranking that comes back is the exact
        one.  Ordering is (y32 descending, row index ascending) — the same
        first-wins rule the on-chip AMAX uses for equal values
        (ref/gen_layer_script.py:479-482 "strictly-greater update -> first
        max wins").
        """
        k = int(k)
        if k < 1:
            raise HeadCacheError("k must be >= 1")
        n = min(self.spec.nrows, k + int(margin))
        p = self.p_f32(x8)
        cand = np.argpartition(p, -n)[-n:]
        y32, _pp = self.exact_rows(cand, x8)
        order = np.lexsort((cand, -y32.astype(np.int64)))
        sel = order[:k]
        return y32[sel].astype(np.int32), cand[sel].astype(np.int64)

    def argmax(self, x8):
        """(row, y32) the chip's AMAXL would report for this activation."""
        v, i = self.topk(x8, 1)
        return int(i[0]), int(v[0])

    def logits(self, values, e_x):
        """int32 y32 -> float64 logits (S4)."""
        return (np.asarray(values, dtype=np.float64)
                * self.spec.logit_scale(e_x))


def open_head(prefix, wid=HEAD_WID, cache=True, cache_dir_=None, mmap=False,
              threads=DEFAULT_THREADS, log=print):
    """The one entry point: spec -> cache hit or build -> ready HostHead."""
    spec, _man = load_spec(prefix, wid)
    h = HostHead(spec, log=log)
    if threads:
        h.threads, h.thread_how = set_blas_threads(threads)
        log(f"  head blas  threads={h.threads} via {h.thread_how}")
        try:
            nodes = len([d for d in os.listdir("/sys/devices/system/node")
                         if d.startswith("node") and d[4:].isdigit()])
        except OSError:                                        # pragma: no cover
            nodes = 1
        if nodes > 1:
            log(f"  head hint  {nodes} NUMA nodes: the 1 GB copy lands on one "
                f"of them, so the GEMV runs at that node's bandwidth.  "
                f"`numactl --interleave=all` measured 10.3 ms vs 17.9 ms on "
                f"snoke — worth it for --verify-head, irrelevant for greedy.")
    cdir = None
    if cache:
        cdir = cache_dir(cache_dir_, log=log)
        p = h.cache_path(cdir)
        if h.load_cache(p, mmap=mmap):
            return h
    h.build()
    if cache:
        try:
            h.save_cache(h.cache_path(cdir))
        except OSError as e:                                   # pragma: no cover
            log(f"  head cache NOT written ({e}); rebuilding every session")
    return h


# ======================================================================
def _selftest(prefix=None, log=print):
    """Board-free checks of THIS file (chat_seq --selftest runs them too)."""
    npass = nfail = 0

    def check(name, cond, detail=""):
        nonlocal npass, nfail
        if cond:
            npass += 1
        else:
            nfail += 1
            log(f"    FAIL {name}: {detail}")
        return cond

    log("head_cache selftest (no board, no head image needed for [1]-[3]):")
    # ---- 1. dequant algebra ----
    class _S(object):
        e, sh = -4, 5

        def logit_exp(self, e_x):
            return self.e + self.sh - 15 + int(e_x) - RS_F
    s = _S()
    check("S4: logit exponent is e_x - 22 for the committed head",
          [s.logit_exp(x) for x in (0, 5, 15)] == [-22, -17, -7],
          str([s.logit_exp(x) for x in (0, 5, 15)]))
    check("RS_F is the residual-stream fraction from ref/layer_fixed",
          RS_F == 8, str(RS_F))
    # ---- 2. cache dir is local ----
    cd = cache_dir(log=lambda *a: None)
    check("cache dir is on a LOCAL filesystem",
          not is_network_fs(cd), f"{cd} is {_fstype(cd)}")
    check("the NFS share would be refused",
          is_network_fs(TOP_DIR) == (_fstype(TOP_DIR).startswith("nfs")),
          _fstype(TOP_DIR))
    # ---- 3. exact arithmetic on a synthetic head ----
    rng = np.random.default_rng(4)
    N, K, G = 64, 256, 128
    w4 = rng.integers(-8, 8, size=(N, K)).astype(np.int8)
    m = rng.integers(1, 65535, size=(N, K // G)).astype(np.uint16)
    img, stride = W4.pack_ddr_rows(w4, m, g=G)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fn = os.path.join(td, "synth_w0.bin")
        with open(fn, "wb") as f:
            f.write(img)
        spec = HeadSpec(0, {"file": "synth_w0.bin", "nrows": N, "k": K,
                            "stride": stride, "sh": 5, "e": -4,
                            "ng": K // 128}, td)
        h = HostHead(spec, log=lambda *a: None)
        h.build(verbose=False)
        x8 = rng.integers(-127, 128, size=K).astype(np.int8)
        want = W4.matvec_y32(w4, m, spec.sh, x8, g=G)
        got, _p = h.exact_rows(np.arange(N), x8)
        check("exact_rows == w4a8_ref.matvec_y32 on every row",
              np.array_equal(got, want), str(np.nonzero(got != want)[0][:8]))
        check("exact_all == matvec_y32", np.array_equal(h.exact_all(x8), want))
        pf = h.p_f32(x8)
        check("f32 ranks the synthetic head like the exact integers",
              int(np.argmax(pf)) == int(np.argmax(want)),
              f"{int(np.argmax(pf))} vs {int(np.argmax(want))}")
        v, i = h.topk(x8, 8)
        order = np.lexsort((np.arange(N), -want.astype(np.int64)))[:8]
        check("topk returns the exact top-8 in (value desc, index asc) order",
              np.array_equal(i, order) and np.array_equal(v, want[order]),
              f"{i.tolist()} vs {order.tolist()}")
        check("argmax agrees with the exact scan",
              h.argmax(x8) == (int(order[0]), int(want[order[0]])))
        lg = h.logits(v, 5)
        check("logits are y32 * 2^(e+sh-15+e_x-RS_F)",
              np.allclose(lg, v.astype(np.float64) * 2.0 ** (-4 + 5 - 15 + 5 - 8)))
        # cache round trip
        p = h.cache_path(td)
        h.save_cache(p)
        h2 = HostHead(spec, log=lambda *a: None)
        check("a fresh HostHead loads the cache", h2.load_cache(p))
        check("the cached f32 is byte-identical", np.array_equal(h.f32, h2.f32))
        os.utime(spec.path, ns=(0, 12345))
        h3 = HostHead(spec, log=lambda *a: None)
        check("a touched (but unchanged) image keeps the cache — an NFS "
              "mtime is advisory, the content fingerprint decides",
              h3.load_cache(p))
        with open(spec.path, "r+b") as f:      # change one weight nibble
            f.seek(0)
            b = f.read(1)
            f.seek(0)
            f.write(bytes([b[0] ^ 0x0F]))
        h4 = HostHead(spec, log=lambda *a: None)
        check("a CHANGED source image invalidates the cache",
              not h4.load_cache(p))
    # ---- 4. the real head, if it is there ----
    if prefix and os.path.exists(prefix + ".weights.json"):
        spec, _ = load_spec(prefix)
        check("the committed head is 248320x1024 e=-4 sh=5 g=128",
              (spec.nrows, spec.k, spec.e, spec.sh, spec.g)
              == (248320, 1024, -4, 5, 128), str(spec.as_dict()))
        check("the committed head dequants with 2^(e_x-22)",
              spec.logit_exp(0) == -22, str(spec.logit_exp(0)))
        if os.path.exists(spec.path):
            h = HostHead(spec, log=lambda *a: None)
            h.open_image()
            # spot-check 3 rows of the REAL image against a hand unpack
            idx = np.array([0, 95928, spec.nrows - 1])
            w4, m = h.rows_w4_m(idx)
            raw = np.asarray(h.src[idx])
            lo = (raw[:, :spec.wb * 64] & 0xF).astype(np.int8)
            check("row unpack: low nibble is the even k",
                  np.array_equal(np.where(lo > 7, lo - 16, lo), w4[:, 0::2]))
            check("scale mantissas are the uint16 tail of the row",
                  np.array_equal(m, raw[:, spec.wb * 64:spec.wb * 64
                                        + 2 * spec.nscale].copy()
                                 .view(np.uint16)))
            check("every row byte past the scale beats is zero padding",
                  int(raw[:, spec.wb * 64 + 2 * spec.nscale:].max()) == 0)
    log(f"  head_cache selftest: {npass} passed, {nfail} failed")
    return npass, nfail


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", default=os.path.join(TOP_DIR, "tb", "scripts",
                                                     "model_v2_s1"))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--bench", action="store_true",
                    help="build/load the real head and time the GEMV")
    ap.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--mmap", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.bench:
        _p, _f = _selftest(a.prefix)
        raise SystemExit(1 if _f else 0)
    h = open_head(a.prefix, cache=not a.no_cache, mmap=a.mmap,
                  threads=a.threads)
    rng = np.random.default_rng(7)
    x8 = np.clip(np.round(rng.standard_normal(h.spec.k) * 30.0),
                 -127, 127).astype(np.int8)
    for tag, fn in (("p_f32", lambda: h.p_f32(x8)),
                    ("topk(32)", lambda: h.topk(x8, 32)),
                    ("argmax", lambda: h.argmax(x8))):
        for _ in range(2):
            fn()
        ts = []
        for _ in range(7):
            t0 = time.perf_counter()
            fn()
            ts.append(time.perf_counter() - t0)
        ts.sort()
        print(f"  {tag:<10s} median {ts[3] * 1e3:7.3f} ms  min "
              f"{ts[0] * 1e3:7.3f} ms")
    t0 = time.perf_counter()
    ya = h.exact_all(x8)
    print(f"  exact_all  {time.perf_counter() - t0:.2f} s   argmax "
          f"{int(np.argmax(ya))} y32 {int(ya.max())}")
    v, i = h.topk(x8, 32)
    print(f"  topk(32)   values {v[:5].tolist()} idx {i[:5].tolist()}")
    ex = np.lexsort((np.arange(len(ya)), -ya.astype(np.int64)))[:32]
    print(f"  vs exact   {'MATCH' if np.array_equal(i, ex) else 'DIFFER'}")
