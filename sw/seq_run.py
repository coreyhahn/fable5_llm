#!/usr/bin/env python3
"""seq_run.py — host-side runner for the on-chip command sequencer (rung 1).

    uv run python seq_run.py --prefix ../tb/scripts/w4/model_v2_s1.e --dry-run
    uv run python seq_run.py --prefix ../tb/scripts/w4/model_v2_s1.e

What it does, in order:

  1. LOAD      <prefix>.seq / .seqdata.bin / .seq.json, check both sha256s
               against the metadata and run ref/seq_format.validate_stream.
  2. PLAN      pack the weight images with sw/layer_test.py:plan_weights (the
               SAME layout the emitter's MVGO records were built against, and
               the plan is ASSERTED equal to meta["weights"]), and place the
               stream + the LDC constant blob at hwmap.SEQ_STREAM_BASE /
               hwmap.SEQ_DATA_BASE.
  3. RELOCATE  the emitter bakes ABSOLUTE chan-0 addresses (ref/seq_format.py
               _Blob.base = SEQ_DATA_BASE = 0x8000_0000, on_embed =
               HW.EMB_BASE, on_matvec = plan_weights_from_wids ->
               HW.W_BASE), so every LDC
               (and EMB, if it ever moves) record is rebased by the difference
               between where the emitter said the blob lives and where this
               runner actually puts it.  MVGO WBASEs are ASSERTED, never
               patched: if the host pack and the stream disagree the stream is
               simply wrong for these weights.
  4. UPLOAD    weights + embedding + blob + relocated stream over h2c, each
               range READ BACK over c2h and compared (sha256 per range).
  5. RUN       BASE/LEN/ENTRY -> START -> poll STATUS -> drain OUT_FIFO.
               While SEQ_STATUS.busy the host touches NOTHING but the SEQ's own
               CSR block (docs/SEQ_ISA.md "Arbitration + clocks").
  6. VERIFY    generated tokens vs <prefix>.seq.json "expect_tokens", with a
               first-divergence report; optionally the whole post-halt
               architectural state against a <prefix>.chip golden
               (tb/scripts/gen_seq_chip_vectors.py), read through the layer
               CSRs AFTER the sequencer has halted.

BOARD SAFETY
  * This tool NEVER programs the FPGA, never touches flash, never runs sudo
    and never calls pcie_helper.sh.
  * The identity gate refuses to touch anything unless MAGIC / CALIB / the
    layer IDENT / all four matvec IDENTs read back exactly.
  * SEQ CSRs (0x6000) DO NOT EXIST before build_029.  Every access to them is
    gated on VERSION == EXPECTED_SEQ_VERSION *and* the seq IDENT, and
    --dry-run performs ZERO accesses to that window — so --dry-run is the
    mode that is safe on the currently resident bitstream.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import numpy as np

SW_DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(os.path.dirname(SW_DIR), "ref")
for _p in (SW_DIR, REF_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hwmap as HW                                             # noqa: E402
from hwmap import (                                            # noqa: E402
    R_MAGIC, R_VERSION, R_CALIB, MAGIC, CALIB_ALL,
    R_IDENT, MV_IDENT0, mv_base,
    L_STAT, L_SPTR, L_SWIN, L_EOUT, L_TCNT, L_IDENT, L_AMAXI, L_AMAXV,
    L_LAYER, L_XRFI, L_XRFD, LAYER_IDENT, SCRATCH_WORDS,
    S_CTRL, S_STATUS, S_BASE_LO, S_BASE_HI, S_LEN, S_PC, S_OUT_FIFO,
    S_OUT_CNT, S_TCNT_SEQ, S_ENTRY, S_IDENT, S_PERF_CYC, S_PERF_REC,
    S_PERF_AXW, S_PERF_AXR, S_PERF_FST, S_XRF0, s_xrf,
    SEQ_IDENT, SEQ_XRF_N, SEQ_OUT_DEPTH, SEQ_CTRL_START, SEQ_CTRL_ABORT,
    SEQ_ST_BUSY, SEQ_OUT_VALID, SEQ_OUT_TOK_MASK, SEQ_PERF_XRF_OVF,
    SEQ_ST_OUTCNT_MASK, SEQ_ST_OF_OVF,
    seq_status, seq_err_name,
    CH_STRIDE, W_BASE, EMB_BASE, SEQ_STREAM_BASE, SEQ_DATA_BASE,
    SEQ_STREAM_MAX, SEQ_DATA_MAX, SEQ_REC_BYTES, SEQ_ALIGN, ACLK_HZ,
)
import seq_format as SF                                        # noqa: E402
from layer_test import plan_weights                            # noqa: E402
from tok_meter import split_rows                               # noqa: E402
# split_rows is the PROVEN 4-chan row partition (tok_meter.py:77, measured
# 12.23 tok/s): contiguous rows across nch channels, the first nrows%nch
# channels taking one extra row.  Importing it (rather than re-deriving it)
# guarantees the host upload lands each engine's rows at the SAME channel-
# local byte offset the emitter's MVGO WBASEs point at.


# ======================================================================
# >>>>>>>>>>>>>>>>>>>>>>  ORCHESTRATOR: FILL THIS IN  <<<<<<<<<<<<<<<<<<
# ======================================================================
# The csr_0 VERSION word of the FIRST netlist that contains seq_0 (build_029).
# It is the low 32 bits of that netlist's git hash, exactly as
# synth/scripts/create_project.tcl stamps it into csr_block and exactly as
# sw/infer.py:EXPECT_VERSION records 0x67A943BD for build_028.
#
# Leave it None until build_029 is programmed:
#   * --dry-run keeps working (DDR uploads + readback verify only, and it
#     performs no access whatsoever to the 0x6000 window), and
#   * any attempt to touch a SEQ CSR aborts with an explicit message.
EXPECTED_SEQ_VERSION = 0x33D720E5  # build_033 netlist (rung4 zero-bubble + TOPK)
# ======================================================================

# Bitstreams WITHOUT a sequencer (pre-build_029, e.g. build_028).  They have
# no sequencer; it is listed only so --dry-run can say "yes, I know what this
# is, and I am deliberately not touching 0x6000".
KNOWN_NO_SEQ_VERSIONS = {
    0x67A943BD: "build_028_rr_SSI_HighUtilSLRs (no seq_0)",
}

DEFAULT_TIMEOUT = 120.0          # s; model_v2_s1.e is ~0.73 s of device time
POLL_S = 0.002
DMA_CHUNK = 64 << 20


class SeqError(RuntimeError):
    pass


# ======================================================================
# artifacts + planning  (PURE PYTHON — unit-tested by --selftest)
# ======================================================================
def derive_base(prefix):
    """Generator-artifact prefix for a SEQ prefix.

    The emitter writes `<base>.<variant>.seq` (SEQ_EMIT=.../model_v2_s1.e)
    beside the generator's `<base>.txt` / `<base>.weights.json` /
    `<base>_w*.bin` / `<base>.emb.bin`: the base is the SEQ prefix minus its
    last dotted
    component — unless the SEQ prefix already carries the artifacts itself.
    """
    if os.path.exists(prefix + ".weights.json"):
        return prefix
    d, name = os.path.split(prefix)
    head, dot, _tail = name.rpartition(".")
    if not dot:
        return prefix
    return os.path.join(d, head)


class Artifacts(object):
    """<prefix>.seq + .seqdata.bin + .seq.json, hash-checked and validated."""

    def __init__(self, prefix, base=None):
        self.prefix = prefix
        self.base = derive_base(prefix) if base is None else base
        self.meta = json.load(open(prefix + ".seq.json"))
        self.stream = open(prefix + ".seq", "rb").read()
        self.blob = open(prefix + ".seqdata.bin", "rb").read()
        m = self.meta
        got = hashlib.sha256(self.stream).hexdigest()
        if got != m["stream_sha256"]:
            raise SeqError(f"{prefix}.seq sha256 {got[:16]} != metadata "
                           f"{m['stream_sha256'][:16]}")
        got = hashlib.sha256(self.blob).hexdigest()
        if got != m["seqdata_sha256"]:
            raise SeqError(f"{prefix}.seqdata.bin sha256 {got[:16]} != "
                           f"metadata {m['seqdata_sha256'][:16]}")
        if len(self.stream) != m["stream_bytes"] or \
                len(self.stream) != m["nrec"] * SEQ_REC_BYTES:
            raise SeqError(f"{prefix}.seq is {len(self.stream)} B, metadata "
                           f"says {m['nrec']} records "
                           f"({m['nrec'] * SEQ_REC_BYTES} B)")
        self.recs = SF.unpack_stream(self.stream)
        SF.validate_stream(self.recs)
        self.manifest = json.load(open(self.base + ".weights.json"))
        self.wdir = os.path.dirname(os.path.abspath(self.base)) or "."
        self.embf = self.base + ".emb.bin"
        if not os.path.exists(self.embf):
            self.embf = None

    @property
    def nrec(self):
        return len(self.recs)

    def halt_pc(self):
        """Record index of the LAST HALT — what a cleanly halted PC reads."""
        pcs = [i for i, r in enumerate(self.recs) if r.opcode == SF.OP_HALT]
        if not pcs:
            raise SeqError("stream has no HALT record")
        return pcs[-1]


def expected_tokens(meta):
    """The token ids the OUT FIFO must produce, in order.

    The emitter appends one entry per AMAXL at EMISSION time (before
    `_try_loop` collapses identical trailing bodies), so this list is the
    DYNAMIC expectation — `len(expect_tokens)` is steps, not the number of
    AMAXL records left in the stream.
    """
    return [int(t) for t in meta.get("expect_tokens", [])]


def plan_ddr(meta, stream_bytes, blob_bytes, chan=0,
             stream_base=SEQ_STREAM_BASE, data_base=SEQ_DATA_BASE,
             emb_base=EMB_BASE):
    """Where every SEQ artifact goes, and by how much the stream moves.

    Channel-local addresses plus `ddr_off = chan * CH_STRIDE`, because
    seq_0/m_axi has the SAME 16 GiB four-channel view XDMA M_AXI has
    (synth/scripts/create_project.tcl), while mvchan_c/m_axi sees its own
    channel at 0 — so MVGO WBASEs stay channel-local and the fetch / LDC /
    EMB addresses do not.

    `chan` is the FETCH channel: the single channel seq_0/m_axi reads the
    record stream, the LDC const blob and the embedding table from.

    Weight placement depends on meta["nch"] (default 1):
      * nch == 1 — the classic single-channel stream.  Its MVGO records
        address matvec_chan `meta["chan"]`, whose DDR is channel
        `meta["chan"]`, so the weight image and the fetch path share that
        one channel and --chan must select it.
      * nch  > 1 — a row-split stream (rung 1b).  Its MVGO records address
        matvec_chan 0..nch-1, each of which reads its OWN DDR channel at
        offset 0, so every weight image is ROW-SPLIT across channels
        0..nch-1 (split_rows) while the fetch path stays on the single
        channel `meta["chan"]`.  WBASEs are still channel-local; only the
        host DMA adds `c * CH_STRIDE` per weight quarter (done in upload()).
    """
    if chan not in (0, 1, 2, 3):
        raise SeqError(f"DDR fetch channel {chan} out of range")
    nch = int(meta.get("nch", 1))
    if nch not in (1, 2, 3, 4):
        raise SeqError(f"meta nch={nch} out of range (1..4)")
    mchan = int(meta.get("chan", 0))
    if nch == 1:
        if mchan != chan:
            raise SeqError(
                f"the stream was emitted for engine channel {mchan} "
                f"but --chan is {chan}: MVGO records address matvec_chan "
                f"{mchan}, whose DDR is channel {mchan}")
        weight_chans = [chan]
    else:
        # A row-split stream fetches from the emitter's single `chan` while
        # its weights live on channels 0..nch-1.  --chan selects the fetch
        # channel and must match the emitter's.
        if mchan != chan:
            raise SeqError(
                f"the {nch}-channel stream fetches from channel {mchan} "
                f"(the emitter's chan) but --chan is {chan}; pass "
                f"--chan {mchan}")
        weight_chans = list(range(nch))
    for name, b in (("stream", stream_base), ("blob", data_base)):
        if b % SEQ_ALIGN:
            raise SeqError(f"SEQ {name} base {b:#x} is not {SEQ_ALIGN}B "
                           f"aligned")
    if stream_bytes > SEQ_STREAM_MAX:
        raise SeqError(f"stream is {stream_bytes} B, window at "
                       f"{stream_base:#x} is {SEQ_STREAM_MAX} B")
    if blob_bytes > SEQ_DATA_MAX:
        raise SeqError(f"const blob is {blob_bytes} B, window at "
                       f"{data_base:#x} is {SEQ_DATA_MAX} B")
    regions = [("stream", stream_base, stream_bytes),
               ("seqdata", data_base, blob_bytes)]
    for i, (na, a, la) in enumerate(regions):
        for (nb, b, lb) in regions[i + 1:]:
            if la and lb and a < b + lb and b < a + la:
                raise SeqError(f"SEQ {na} [{a:#x},{a + la:#x}) overlaps "
                               f"{nb} [{b:#x},{b + lb:#x})")
    ddr_off = chan * CH_STRIDE
    return {
        "chan": chan,                               # the FETCH channel
        "nch": nch,                                 # weight row-split width
        "weight_chans": weight_chans,               # channels weights land on
        # rung 4 S4: {} for every pre-rung-4 / nch==1 stream (all contiguous)
        "weight_layout": dict(meta.get("weight_layout") or {}),
        "ddr_off": ddr_off,
        "stream_base": stream_base,
        "data_base": data_base,
        "emb_base": emb_base,
        "seq_base": ddr_off + stream_base,          # what SEQ_BASE_LO/HI get
        "data_delta": (ddr_off + data_base) - int(meta["seq_data_base"]),
        "emb_delta": (ddr_off + emb_base) - int(meta["emb_base"]),
        "stream_bytes": stream_bytes,
        "blob_bytes": blob_bytes,
    }


def layout_of(meta, wid):
    """The placement rung 4 S4 recorded for one weight image.

    Streams older than rung 4 (and every nch==1 stream) carry no
    "weight_layout" key at all -> LAYOUT_CONTIG, i.e. rung 1b's behaviour,
    bit-for-bit.
    """
    wl = (meta or {}).get("weight_layout") or {}
    by = wl.get("by_wid") or {}
    return by.get(str(wid), wl.get("default", SF.LAYOUT_CONTIG))


def plan_weight_split(manifest, wbase_of, nch, weight_chans, meta=None):
    """The per-channel uploads for every weight image (PURE).

    For image `wid` (nrows, stride), `seq_format.weight_pieces` returns the
    (channel index, r0, nrows) pieces the EMITTER's MVGO WBASEs imply, so
    the host cannot drift from the stream:

      * LAYOUT_CONTIG (rung 1b, and every non-head matvec): one contiguous
        row-quarter per channel — split_rows, tok_meter.py:264-285 exactly.
      * LAYOUT_ILV (rung 4 S4, the LM head): one piece per 2048-row engine
        chunk, chunk j on channel j % nch, so a channel's rows are STRIDED
        through the image instead of contiguous.

    Either way a piece is the file slice [r0*stride, (r0+n)*stride) and
    lands at

        abs_addr = chan * CH_STRIDE + wbase_of[wid] + r0*stride
        local_addr =                  wbase_of[wid] + r0*stride

    `local_addr` is exactly what that channel's MVGO WBASE points at
    (channel-local, row-aligned inside the packed image), so the bytes each
    engine reads are the bytes the host wrote.  Zero-row channels
    (nrows < nch) are dropped.  Returns a list of dicts, one per write.
    """
    out = []
    for wid_s, m in sorted(manifest.items(), key=lambda kv: int(kv[0])):
        wid = int(wid_s)
        nrows, stride = int(m["nrows"]), int(m["stride"])
        lay = layout_of(meta, wid)
        depth = int(((meta or {}).get("weight_layout") or {})
                    .get("chunk_rows", SF.CHUNK_ROWS))
        for (i, r0, n) in SF.weight_pieces(nrows, nch, lay, depth):
            c = weight_chans[i]
            byte_off = r0 * stride
            local = wbase_of[wid] + byte_off
            out.append({"wid": wid, "chan": c, "r0": r0, "nrows_piece": n,
                        "stride": stride, "byte_off": byte_off,
                        "byte_len": n * stride, "local_addr": local,
                        "abs_addr": c * CH_STRIDE + local, "layout": lay})
    return out


def _disjoint(ranges):
    """True when sorted [(addr, len)] pairs do not overlap."""
    return all(ranges[i][0] + ranges[i][1] <= ranges[i + 1][0]
               for i in range(len(ranges) - 1))


def _rec_addr64(r):
    return (int(r.len_or_addr_hi) << 32) | int(r.addr_lo)


def relocate(recs, meta, plan, blob_bytes):
    """Rebase the stream's baked absolute DDR addresses onto `plan`.

    Returns (new_recs, report).  LDC/EMB are PATCHED; MVGO is only checked
    against the caller's weight plan (see `check_weight_plan`).
    """
    old_data = int(meta["seq_data_base"])
    d_data, d_emb = plan["data_delta"], plan["emb_delta"]
    out, n_ldc, n_ldc_ind, n_emb = [], 0, 0, 0
    lo_off, hi_off = None, None
    for i, r in enumerate(recs):
        if r.opcode == SF.EXT_LDC:
            a = _rec_addr64(r)
            off = a - old_data
            if not (0 <= off < max(1, blob_bytes)):
                raise SeqError(
                    f"rec {i}: LDC reads {a:#x}, outside the emitter's "
                    f"{blob_bytes} B blob at {old_data:#x}  [{SF.disasm(r)}]")
            n_words = int(r.imm32)
            if r.ind == SF.IND_NONE and off + 2 * n_words > blob_bytes:
                raise SeqError(
                    f"rec {i}: LDC {a:#x}+{2 * n_words}B runs past the end of "
                    f"the {blob_bytes} B blob  [{SF.disasm(r)}]")
            if r.ind != SF.IND_NONE:
                # A10 position cursor: addr_lo is the FIRST step's table and
                # XRF[4] strides it.  Only the base can be checked statically.
                n_ldc_ind += 1
            na = a + d_data
            if na & 1:
                raise SeqError(f"rec {i}: relocated LDC address {na:#x} is "
                               f"odd (seq_unit raises err 0x0B)")
            if na >> 34:
                raise SeqError(f"rec {i}: relocated LDC address {na:#x} does "
                               f"not fit the 34-bit AXI4 master")
            lo_off = off if lo_off is None else min(lo_off, off)
            hi_off = (off + 2 * n_words if hi_off is None
                      else max(hi_off, off + 2 * n_words))
            out.append(SF.Rec(SF.EXT_LDC, flags=r.flags, target=r.target,
                              imm32=r.imm32, addr_lo=na & 0xFFFFFFFF,
                              len_or_addr_hi=na >> 32))
            n_ldc += 1
        elif r.opcode == SF.OP_EMB:
            base = (int(r.target) << 32) | int(r.imm32)
            if base != int(meta["emb_base"]):
                raise SeqError(
                    f"rec {i}: EMB base {base:#x} != the metadata's "
                    f"{int(meta['emb_base']):#x}  [{SF.disasm(r)}]")
            nb = base + d_emb
            if nb >> 34 or (nb & 1):
                raise SeqError(f"rec {i}: relocated EMB base {nb:#x} is "
                               f"unusable")
            out.append(SF.Rec(SF.OP_EMB, flags=r.flags,
                              target=nb >> 32, imm32=nb & 0xFFFFFFFF,
                              addr_lo=r.addr_lo,
                              len_or_addr_hi=r.len_or_addr_hi))
            n_emb += 1
        else:
            out.append(r)
    SF.validate_stream(out)
    return out, {"ldc": n_ldc, "ldc_indirected": n_ldc_ind, "emb": n_emb,
                 "data_delta": d_data, "emb_delta": d_emb,
                 "blob_span": None if lo_off is None else (lo_off, hi_off)}


def check_weight_plan(meta, wbase_of, manifest):
    """MVGO WBASEs are ASSERTED against the host's own pack, never patched."""
    mplan = {int(k): v for k, v in meta.get("weights", {}).items()}
    if not mplan:
        return {"images": 0, "note": "stream carries no weight plan"}
    bad = []
    for wid, p in sorted(mplan.items()):
        host = wbase_of.get(wid)
        if host is None:
            bad.append(f"wid {wid}: in the stream plan, absent from "
                       f"{len(wbase_of)} packed manifest images")
        elif int(p["base"]) != int(host):
            bad.append(f"wid {wid}: stream WBASE {int(p['base']):#x} != host "
                       f"pack {int(host):#x}")
        else:
            m = manifest[str(wid)] if str(wid) in manifest else manifest[wid]
            for k in ("nrows", "ng", "sh", "stride"):
                if int(p[k]) != int(m[k]):
                    bad.append(f"wid {wid}: stream {k}={p[k]} != manifest "
                               f"{m[k]}")
            if int(p.get("g", 128)) != int(m.get("g", 128)):
                bad.append(f"wid {wid}: stream g={p.get('g', 128)} != "
                           f"manifest g={m.get('g', 128)}")
    if bad:
        raise SeqError("the SEQ stream and the weight pack disagree "
                       "(regenerate one of them):\n  " + "\n  ".join(bad[:12]))
    return {"images": len(mplan)}


def check_mvgo_targets(recs, wbase_of, manifest):
    """Every MVGO WBASE must be a row-aligned offset inside a packed image."""
    imgs = []
    for wid, base in sorted(wbase_of.items()):
        m = manifest[str(wid)] if str(wid) in manifest else manifest[wid]
        imgs.append((int(base), int(base) + int(m["nrows"]) * int(m["stride"]),
                     int(m["stride"]), int(wid)))
    n = 0
    for i, r in enumerate(recs):
        if r.opcode != SF.OP_MVGO:
            continue
        wb = ((int(r.len_or_addr_hi) & 0xFF) << 32) | int(r.addr_lo)
        hit = [t for t in imgs if t[0] <= wb < t[1]]
        if not hit:
            raise SeqError(f"rec {i}: MVGO WBASE {wb:#x} is outside every "
                           f"packed weight image  [{SF.disasm(r)}]")
        lo, _hi, stride, wid = hit[0]
        if (wb - lo) % stride:
            raise SeqError(f"rec {i}: MVGO WBASE {wb:#x} is not row-aligned "
                           f"in wid {wid} (stride {stride})  [{SF.disasm(r)}]")
        n += 1
    return n


def first_divergence(got, want, a_name="chip", b_name="expected"):
    """Human-readable first difference between two token sequences."""
    got, want = list(got), list(want)
    if got == want:
        return None
    n = min(len(got), len(want))
    for i in range(n):
        if got[i] != want[i]:
            lo = max(0, i - 3)
            return (f"first divergence at token {i}: {a_name}={got[i]} "
                    f"{b_name}={want[i]}\n"
                    f"    {a_name}[{lo}:{i + 4}] = {got[lo:i + 4]}\n"
                    f"    {b_name}[{lo}:{i + 4}] = {want[lo:i + 4]}")
    return (f"{a_name} produced {len(got)} tokens, {b_name} has {len(want)} "
            f"(common prefix of {n} identical)\n"
            f"    {a_name}  = {got}\n    {b_name} = {want}")


def disasm_window(recs, pc, n_before=12, n_after=1):
    """Disassemble [pc-n_before, pc+n_after] with the ARG0..2 shadow.

    The shadow is rebuilt by a STATIC scan from record 0, so after a taken
    JMP it is the shadow of the fall-through path, not of the execution
    trace — good enough to read the failing record, flagged in the output.
    """
    lo = max(0, pc - n_before)
    hi = min(len(recs), pc + 1 + n_after)
    ctx = {}
    for r in recs[:lo]:
        if r.opcode == SF.OP_CSRWR:
            if r.target == SF.CSR_L_ARG0:
                ctx["arg0"] = r.imm32
            elif r.target == SF.CSR_L_ARG1:
                ctx["arg1"] = r.imm32
            elif r.target == SF.CSR_L_ARG2:
                ctx["arg2"] = r.imm32
    lines = []
    for i in range(lo, hi):
        r = recs[i]
        mark = "  <<< PC" if i == pc else ""
        lines.append(SF.disasm(r, i, ctx) + mark)
        if r.opcode == SF.OP_CSRWR:
            if r.target == SF.CSR_L_ARG0:
                ctx["arg0"] = r.imm32
            elif r.target == SF.CSR_L_ARG1:
                ctx["arg1"] = r.imm32
            elif r.target == SF.CSR_L_ARG2:
                ctx["arg2"] = r.imm32
    return "\n".join(lines)


def parse_chip_golden(path):
    """Read a tb/scripts/gen_seq_chip_vectors.py <prefix>.chip golden."""
    g = {"xrf": {}, "tok": [], "tcnt": {}, "mem": {}}
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            k = p[0]
            if k == "NREC":
                g["nrec"] = int(p[1])
            elif k == "PC":
                g["pc"] = int(p[1])
            elif k == "BASES":
                g["bases"] = [int(x, 16) for x in p[1:]]
            elif k == "XRF":
                g["xrf"][int(p[1])] = int(p[2], 16)
            elif k == "TOK":
                g["tok"].append(int(p[1], 16))
            elif k == "TCNT":
                g["tcnt"][int(p[1])] = (int(p[2]), int(p[3]))
            elif k == "EOUT":
                g["eout"] = int(p[1], 16)
            elif k == "AMAX":
                g["amax"] = (int(p[1], 16), int(p[2], 16))
            elif k == "MEM":
                g["mem"][int(p[1], 16)] = int(p[2], 16)
            elif k == "END":
                g["end"] = True
    if not g.get("end"):
        raise SeqError(f"{path}: no END line — truncated golden")
    return g


# ======================================================================
# device
# ======================================================================
class Dev(object):
    """XDMA AXI-Lite CSR + DMA access with the board-safety gate.

    `seq_ok` is False until the identity gate has SEEN the build_029 VERSION
    and the seq_unit IDENT; every SEQ CSR accessor refuses while it is False,
    which is what makes --dry-run safe on a bitstream that has no seq_0.
    """

    def __init__(self, path="/dev/xdma0", chan=0, allow_seq=True,
                 expect_version=EXPECTED_SEQ_VERSION, log=print):
        self.chan = chan
        self.log = log
        self.n_rd = self.n_wr = 0
        self.user = os.open(f"{path}_user", os.O_RDWR)
        self.ident, self.seq_ok, self.seq_why = self._gate(expect_version,
                                                           allow_seq)
        self.h2c = os.open(f"{path}_h2c_0", os.O_WRONLY)
        self.c2h = os.open(f"{path}_c2h_0", os.O_RDONLY)
        self.ddr_off = chan * CH_STRIDE

    # ---------------- raw MMIO ----------------
    def rd(self, a):
        self.n_rd += 1
        return int.from_bytes(os.pread(self.user, 4, a), "little")

    def wr(self, a, v):
        self.n_wr += 1
        os.pwrite(self.user, int(v).to_bytes(4, "little"), a)

    # ---------------- identity ----------------
    def _gate(self, expect_version, allow_seq):
        rd = self.rd
        magic, ver, calib = rd(R_MAGIC), rd(R_VERSION), rd(R_CALIB)
        li = rd(L_IDENT)
        mvi = [rd(mv_base(c) + R_IDENT) for c in range(4)]
        bad = []
        if magic != MAGIC:
            bad.append(f"MAGIC={magic:#010x} want {MAGIC:#010x}")
        if calib != CALIB_ALL:
            bad.append(f"CALIB={calib:#x} want {CALIB_ALL:#x}")
        if li != LAYER_IDENT:
            bad.append(f"layer IDENT={li:#010x} want {LAYER_IDENT:#010x}")
        for c, v in enumerate(mvi):
            if v != MV_IDENT0 + c:
                bad.append(f"matvec{c} IDENT={v:#010x} want "
                           f"{MV_IDENT0 + c:#010x}")
        if bad:
            os.close(self.user)
            raise SystemExit(
                "REFUSING TO TOUCH THE BOARD — identity gate failed:\n  "
                + "\n  ".join(bad)
                + "\n(this tool never programs the FPGA; fix the resident "
                  "bitstream out of band)")
        ident = {"magic": magic, "version": ver, "calib": calib,
                 "layer_ident": li, "mv_ident": mvi}
        # ---- the SEQ half of the gate: 0x6000 does not exist before 029 ----
        if not allow_seq:
            return ident, False, "--dry-run: the SEQ CSR window is not touched"
        if expect_version is None:
            return ident, False, (
                "EXPECTED_SEQ_VERSION is still the None placeholder in "
                "sw/seq_run.py — fill it with the build_029 netlist hash")
        if ver != expect_version:
            known = KNOWN_NO_SEQ_VERSIONS.get(ver)
            return ident, False, (
                f"VERSION={ver:#010x}"
                + (f" ({known})" if known else "")
                + f" != EXPECTED_SEQ_VERSION {expect_version:#010x}: this "
                  f"bitstream has no sequencer (or is the wrong one)")
        sid = rd(S_IDENT)
        if sid != SEQ_IDENT:
            return ident, False, (f"seq IDENT={sid:#010x} want "
                                  f"{SEQ_IDENT:#010x}")
        ident["seq_ident"] = sid
        return ident, True, "ok"

    def require_seq(self, what):
        if not self.seq_ok:
            raise SystemExit(f"REFUSING {what}: {self.seq_why}")

    # ---------------- DDR ----------------
    def dma_write(self, addr, data):
        n = os.pwrite(self.h2c, data, self.ddr_off + addr)
        if n != len(data):
            raise SeqError(f"short DMA write {n}/{len(data)} @ {addr:#x}")

    def dma_read(self, addr, nbytes):
        b = os.pread(self.c2h, nbytes, self.ddr_off + addr)
        if len(b) != nbytes:
            raise SeqError(f"short DMA read {len(b)}/{nbytes} @ {addr:#x}")
        return b

    def dma_verify(self, addr, data, tag=""):
        """Read `len(data)` bytes back and compare, in DMA_CHUNK pieces."""
        off = 0
        while off < len(data):
            n = min(DMA_CHUNK, len(data) - off)
            got = self.dma_read(addr + off, n)
            if got != data[off:off + n]:
                a = np.frombuffer(got, dtype=np.uint8)
                b = np.frombuffer(data[off:off + n], dtype=np.uint8)
                i = int(np.nonzero(a != b)[0][0])
                raise SeqError(
                    f"DDR readback mismatch {tag} @ {addr + off + i:#x}: "
                    f"got {int(a[i]):#04x} want {int(b[i]):#04x} "
                    f"({int((a != b).sum())} bad bytes in this {n} B chunk)")
            off += n
        return hashlib.sha256(data).hexdigest()

    # ---- channel-explicit DDR (weights row-split across channels) ----
    # dma_write/read above add `self.ddr_off` (the FETCH channel) so the
    # stream/blob/emb follow the sequencer's fetch view.  A row-split weight
    # image instead lands on channels 0..nch-1 at ABSOLUTE `c*CH_STRIDE +
    # local_addr`, so these variants take the channel explicitly and ignore
    # self.ddr_off.  (nch==1 -> chan == the fetch channel, so the abs address
    # is identical to what dma_write produced before this change.)
    def dma_write_chan(self, chan, addr, data):
        base = chan * CH_STRIDE + addr
        n = os.pwrite(self.h2c, data, base)
        if n != len(data):
            raise SeqError(f"short DMA write {n}/{len(data)} @ ch{chan} "
                           f"{addr:#x}")

    def dma_read_chan(self, chan, addr, nbytes):
        """Raw read at the ABSOLUTE ch*CH_STRIDE+addr (residency probes)."""
        got = os.pread(self.c2h, nbytes, chan * CH_STRIDE + addr)
        self.n_rd += 1
        if len(got) != nbytes:
            raise SeqError(f"short DMA read {len(got)}/{nbytes} @ ch{chan} "
                           f"{addr:#x}")
        return got

    def dma_verify_chan(self, chan, addr, data, tag=""):
        """Read back and compare against the ABSOLUTE ch*CH_STRIDE+addr.

        Independent of self.ddr_off (the fetch channel), so a weight quarter
        on any channel is verified where dma_write_chan actually put it.
        """
        base = chan * CH_STRIDE + addr
        off = 0
        while off < len(data):
            n = min(DMA_CHUNK, len(data) - off)
            got = os.pread(self.c2h, n, base + off)
            self.n_rd += 1
            if len(got) != n:
                raise SeqError(f"short DMA read {len(got)}/{n} @ ch{chan} "
                               f"{addr + off:#x}")
            if got != data[off:off + n]:
                a = np.frombuffer(got, dtype=np.uint8)
                b = np.frombuffer(data[off:off + n], dtype=np.uint8)
                i = int(np.nonzero(a != b)[0][0])
                raise SeqError(
                    f"DDR readback mismatch {tag} @ ch{chan} "
                    f"{addr + off + i:#x}: got {int(a[i]):#04x} want "
                    f"{int(b[i]):#04x} ({int((a != b).sum())} bad bytes in "
                    f"this {n} B chunk)")
            off += n
        return hashlib.sha256(data).hexdigest()

    # ---------------- SEQ CSRs ----------------
    def seq_rd(self, a):
        self.require_seq(f"a SEQ CSR read at {a:#x}")
        return self.rd(a)

    def seq_wr(self, a, v):
        self.require_seq(f"a SEQ CSR write at {a:#x}")
        self.wr(a, v)

    def seq_status(self):
        return seq_status(self.seq_rd(S_STATUS))

    def seq_drain_fifo(self, limit=None):
        """Pop every OUT FIFO entry.  Reading S_OUT_FIFO IS the pop."""
        out = []
        # rung 4 S6: OUT FIFO depth 16 -> 64, so the count is 7 bits.
        n = self.seq_rd(S_OUT_CNT) & SEQ_ST_OUTCNT_MASK
        if limit is not None:
            n = min(n, limit)
        for _ in range(n):
            w = self.seq_rd(S_OUT_FIFO)
            if not (w & SEQ_OUT_VALID):
                break
            out.append(w & SEQ_OUT_TOK_MASK)
        return out

    def seq_perf(self):
        fst = self.seq_rd(S_PERF_FST)
        return {"cyc": self.seq_rd(S_PERF_CYC), "rec": self.seq_rd(S_PERF_REC),
                "axil_wr": self.seq_rd(S_PERF_AXW),
                "axil_rd": self.seq_rd(S_PERF_AXR),
                "fetch_starved_cyc": fst >> 1,
                "xrf_ovf": bool(fst & SEQ_PERF_XRF_OVF)}

    def seq_xrf(self):
        return [self.seq_rd(s_xrf(i)) & 0x3FFFF for i in range(SEQ_XRF_N)]

    # ---------------- layer_chan (POST-HALT ONLY) ----------------
    def layer_read_scratch(self, addr, n):
        self.wr(L_SPTR, addr)
        buf = b"".join([os.pread(self.user, 4, L_SWIN) for _ in range(n)])
        self.n_rd += n
        return np.frombuffer(buf, dtype="<u4").astype(np.int64) & 0xFFFF

    def layer_xrf(self, i):
        self.wr(L_XRFI, i)
        return self.rd(L_XRFD) & 0x3FFFF

    def layer_tcnt(self, kv_slot):
        keep = self.rd(L_LAYER)
        self.wr(L_LAYER, (kv_slot << 8) | (keep & 0x1F))
        v = self.rd(L_TCNT)
        self.wr(L_LAYER, keep)
        return (v & 0x3FF, (v >> 16) & 0x3FF)


# ======================================================================
# the run
# ======================================================================
def upload(dev, art, plan, recs, do_weights=True, verify=True, log=print):
    """Weights + embedding + blob + stream -> DDR, readback-checked."""
    rep = {"ranges": [], "bytes": 0, "verified_bytes": 0}
    t0 = time.monotonic()
    wbase_of, wtop = plan_weights(art.manifest, art.wdir)

    def put(name, addr, data):
        dev.dma_write(addr, data)
        rep["bytes"] += len(data)
        h = None
        if verify:
            h = dev.dma_verify(addr, data, tag=name)
            rep["verified_bytes"] += len(data)
        rep["ranges"].append({"name": name, "addr": hex(addr),
                              "bytes": len(data),
                              "sha256": (h or "")[:16] or None})
        return h

    nch = plan["nch"]
    wchans = plan["weight_chans"]
    if do_weights:
        # Each weight image is row-split across `wchans` (nch==1 -> the one
        # fetch channel, byte-identical to the old whole-image write; nch>1 ->
        # channels 0..nch-1, tok_meter.py:264-285).  Placement is a pure
        # function (plan_weight_split) so --selftest can prove the addressing
        # off-board; here we just read each file once and DMA its quarters.
        splits = plan_weight_split(art.manifest, wbase_of, nch, wchans,
                                   art.meta)
        by_wid = {}
        for s in splits:
            by_wid.setdefault(s["wid"], []).append(s)
        nby = 0
        for wid, m in sorted(art.manifest.items(), key=lambda kv: int(kv[0])):
            img = open(os.path.join(art.wdir, m["file"]), "rb").read()
            mv = memoryview(img)
            for s in by_wid[int(wid)]:
                lo, hi = s["byte_off"], s["byte_off"] + s["byte_len"]
                dev.dma_write_chan(s["chan"], s["local_addr"], mv[lo:hi])
                nby += s["byte_len"]
        rep["bytes"] += nby
        if verify:
            h = hashlib.sha256()
            for wid, m in sorted(art.manifest.items(),
                                 key=lambda kv: int(kv[0])):
                img = open(os.path.join(art.wdir, m["file"]), "rb").read()
                for s in by_wid[int(wid)]:
                    lo, hi = s["byte_off"], s["byte_off"] + s["byte_len"]
                    dev.dma_verify_chan(
                        s["chan"], s["local_addr"], img[lo:hi],
                        tag=f"weight {m['file']} ch{s['chan']} "
                            f"rows[{s['r0']},{s['r0'] + s['nrows_piece']})")
                    rep["verified_bytes"] += s["byte_len"]
                h.update(img)                    # full image, wid order
            rep["weights_sha256"] = h.hexdigest()[:16]
        rep["ranges"].append({"name": f"{len(art.manifest)} weight images "
                              f"x {nch} chan" + ("s" if nch > 1 else ""),
                              "addr": hex(W_BASE), "bytes": nby,
                              "sha256": rep.get("weights_sha256"),
                              "chans": list(wchans)})
        ilv = sorted({s["wid"] for s in splits
                      if s.get("layout") == SF.LAYOUT_ILV})
        cs = "chan " + str(wchans[0]) if nch == 1 else \
            f"row-split over chans {wchans}" + (
                f", wid {ilv} chunk-INTERLEAVED (rung 4 S4)" if ilv else "")
        rep["ilv_wids"] = ilv
        rep["weight_writes"] = len(splits)
        log(f"  weights   {len(art.manifest)} images, {nby / 2**20:.0f} MiB "
            f"-> {W_BASE:#x}..{wtop:#x} ({cs})"
            + ("  [readback OK]" if verify else ""))
        if art.embf:
            emb = open(art.embf, "rb").read()
            put("embedding", plan["emb_base"], emb)
            log(f"  embedding {len(emb) / 2**20:.0f} MiB -> "
                f"{plan['emb_base']:#x}"
                + ("  [readback OK]" if verify else ""))
    else:
        log("  weights   SKIPPED (--skip-weights: assumed resident)")

    blob = art.blob
    if blob:
        put("seqdata", plan["data_base"], blob)
    stream = SF.pack_stream(recs)
    put("stream", plan["stream_base"], stream)
    log(f"  seqdata   {len(blob)} B -> {plan['data_base']:#x}"
        + ("  [readback OK]" if verify else ""))
    log(f"  stream    {len(stream)} B ({len(recs)} records) -> "
        f"{plan['stream_base']:#x}"
        + ("  [readback OK]" if verify else ""))
    rep["seconds"] = round(time.monotonic() - t0, 1)
    rep["stream_sha256_relocated"] = hashlib.sha256(stream).hexdigest()
    rep["wbase_of"] = {str(k): hex(v) for k, v in sorted(wbase_of.items())}
    rep["weight_top"] = hex(wtop)
    return rep, wbase_of, stream


def seq_start_and_poll(dev, art, plan, timeout=DEFAULT_TIMEOUT, entry=0,
                       init_xrf=True, log=print):
    """START, poll STATUS while draining OUT_FIFO, return the run report."""
    dev.require_seq("a sequencer run")
    st = dev.seq_status()
    if st["busy"]:
        raise SeqError(f"the sequencer is already busy (STATUS={st['raw']:#x})"
                       " — another host has it, or a previous run hung")
    stale = dev.seq_drain_fifo()
    if stale:
        log(f"  drained {len(stale)} stale OUT FIFO entries: {stale}")
    if init_xrf:
        for i in range(SEQ_XRF_N):
            dev.seq_wr(s_xrf(i), 0)
    dev.seq_wr(S_TCNT_SEQ, 0)
    base = plan["seq_base"]
    dev.seq_wr(S_BASE_LO, base & 0xFFFFFFFF)
    dev.seq_wr(S_BASE_HI, (base >> 32) & 0x3)
    dev.seq_wr(S_LEN, art.nrec)
    dev.seq_wr(S_ENTRY, entry)
    for a, want, nm in ((S_BASE_LO, base & 0xFFFFFFFF, "BASE_LO"),
                        (S_BASE_HI, (base >> 32) & 0x3, "BASE_HI"),
                        (S_LEN, art.nrec, "LEN"),
                        (S_ENTRY, entry, "ENTRY")):
        got = dev.seq_rd(a)
        if got != want:
            raise SeqError(f"SEQ {nm} read back {got:#x}, wrote {want:#x}")
    log(f"  SEQ_BASE={base:#x} LEN={art.nrec} ENTRY={entry} -> START")

    tokens, t0, last_pc, of_hwm, of_ovf = [], time.monotonic(), -1, 0, False
    dev.seq_wr(S_CTRL, SEQ_CTRL_START)
    while True:
        st = dev.seq_status()
        of_hwm = max(of_hwm, st["out_cnt"])
        of_ovf = of_ovf or st.get("of_ovf", False)
        if st["out_cnt"]:
            tokens += dev.seq_drain_fifo()
        if not st["busy"]:
            break
        dt = time.monotonic() - t0
        if dt > timeout:
            pc = dev.seq_rd(S_PC)
            dev.seq_wr(S_CTRL, SEQ_CTRL_ABORT)
            time.sleep(0.05)
            st = dev.seq_status()
            raise SeqError(
                f"sequencer timeout after {dt:.1f}s at pc={pc} "
                f"(STATUS={st['raw']:#010x}, err_code={st['err_code']:#04x} "
                f"{seq_err_name(st['err_code'])}); ABORT was issued\n"
                + disasm_window(art.recs, min(pc, art.nrec - 1)))
        time.sleep(POLL_S)
        pc = dev.seq_rd(S_PC)
        if pc // 4096 != last_pc // 4096:
            last_pc = pc
            log(f"    pc {pc}/{art.nrec}  ({dt:.1f}s)")
    wall = time.monotonic() - t0
    tokens += dev.seq_drain_fifo()
    pc = dev.seq_rd(S_PC)
    perf = dev.seq_perf()
    ctrl = dev.seq_rd(S_CTRL)
    of_ovf = of_ovf or st.get("of_ovf", False)
    run = {"pc": pc, "status": st, "ctrl": ctrl, "tokens": tokens,
           "wall_s": round(wall, 3), "perf": perf,
           "out_fifo_high_water": of_hwm, "out_fifo_ovf": bool(of_ovf),
           "device_ms": round(perf["cyc"] / ACLK_HZ * 1e3, 3)}
    if of_ovf:
        # rung 4 S6: of_ovf is STICKY UNTIL RESET (the xrf_ovf precedent),
        # so this is an alarm about the whole power-on, not this launch: a
        # push found the 64-deep FIFO full and the token was DROPPED.  Every
        # token list read since then is suspect, including this one.
        run["warn_fifo_ovf"] = (
            f"STATUS of_ovf is SET (STATUS={st['raw']:#010x}): the OUT FIFO "
            f"dropped at least one token since the last RESET.  The bit is "
            f"sticky until reset, so it may predate this run — but the token "
            f"stream cannot be trusted until the board is reprogrammed/reset "
            f"and the run repeated.")
        log("  WARNING  " + run["warn_fifo_ovf"])
    elif of_hwm >= SEQ_OUT_DEPTH:
        run["warn_fifo_full"] = (
            f"OUT FIFO reached {of_hwm}/{SEQ_OUT_DEPTH} entries — seq_unit "
            f"DROPS pushes past {SEQ_OUT_DEPTH}, so a token may be missing")
    return run


def failure_report(art, run, n_last=12):
    st = run["status"]
    pc = run["pc"]
    out = [f"SEQ HALTED WITH err_code={st['err_code']:#04x} "
           f"({seq_err_name(st['err_code'])})",
           f"  STATUS={st['raw']:#010x} busy={st['busy']} err={st['err']} "
           f"halted={st['halted']} out_cnt={st['out_cnt']}",
           f"  PC={pc} of {art.nrec} records"]
    if pc < art.nrec:
        out.append(f"  failing record: {SF.disasm(art.recs[pc], pc)}")
        out.append(f"  last {n_last} records issued before it "
                   f"(static ARG shadow — approximate after a taken JMP):")
        out.append(disasm_window(art.recs, pc, n_before=n_last, n_after=1))
    else:
        out.append("  PC is outside the stream (err 0x09): SEQ_LEN or a JMP "
                   "target is wrong")
    out.append(f"  perf: {run['perf']}")
    return "\n".join(out)


def verify_chip_golden(dev, art, run, golden, log=print, mem_limit=None):
    """Post-halt architectural state vs a gen_seq_chip_vectors .chip golden.

    Only called AFTER the sequencer has halted: reading layer_chan CSRs while
    SEQ_STATUS.busy would violate the ISA's arbitration rule.
    """
    bad, checked = [], 0
    if golden.get("nrec") != art.nrec:
        bad.append(f"golden NREC {golden.get('nrec')} != stream {art.nrec}")
    if run["pc"] != golden.get("pc"):
        bad.append(f"PC {run['pc']} != golden {golden.get('pc')}")
    checked += 2
    for i, want in sorted(golden["xrf"].items()):
        got = dev.seq_rd(s_xrf(i)) & 0x3FFFF
        checked += 1
        if got != want:
            bad.append(f"SEQ XRF[{i}] = {got:#07x} want {want:#07x}")
    # layer_chan's XRF is a MIRROR, and only a partial one: seq_unit writes
    # through the entries a RECORD sets (CSRWR to the 0x2nn space, XOP,
    # AMAXL) but NOT the ones it refreshes by reading layer_chan
    # (rtl/seq_unit.sv I_XRFRDW: DYNQ8 -> XRF[0] from EOUT).  So XRF[0] is
    # expected to disagree and the mirror is reported, never gated on.
    mirror = {}
    for i in sorted(golden["xrf"]):
        mirror[i] = dev.layer_xrf(i)
    mism = [i for i, v in mirror.items() if v != golden["xrf"][i]]
    if mism:
        log(f"  mirror    layer_chan XRF differs from the SEQ copy at "
            f"{mism} (informational: index 0 is a read-refresh, not a "
            f"write-through)")
    d = first_divergence(run["tokens"], golden["tok"], "chip", "golden")
    checked += 1
    if d:
        bad.append("OUT FIFO vs golden: " + d)
    for s, (a, b) in sorted(golden["tcnt"].items()):
        got = dev.layer_tcnt(s)
        checked += 1
        if got != (a, b):
            bad.append(f"TCNT[{s}] = {got} want {(a, b)}")
    got = dev.rd(L_EOUT) & 0xF
    checked += 1
    if got != golden.get("eout"):
        bad.append(f"EOUT = {got} want {golden.get('eout')}")
    gi, gv = dev.rd(L_AMAXI) & 0x3FFFF, dev.rd(L_AMAXV)
    checked += 2
    if (gi, gv) != tuple(golden.get("amax", (None, None))):
        bad.append(f"AMAX = ({gi}, {gv:#010x}) want {golden.get('amax')}")
    addrs = sorted(golden["mem"])
    if mem_limit is not None:
        addrs = addrs[:mem_limit]
    if addrs:
        scr = dev.layer_read_scratch(0, SCRATCH_WORDS)
        nbad = 0
        for a in addrs:
            checked += 1
            if int(scr[a]) != golden["mem"][a]:
                nbad += 1
                if nbad <= 8:
                    bad.append(f"scratch[{a:#06x}] = {int(scr[a]):#06x} want "
                               f"{golden['mem'][a]:#06x}")
        if nbad > 8:
            bad.append(f"... {nbad - 8} further scratch mismatches "
                       f"({nbad}/{len(addrs)} checked words differ)")
    log(f"  golden    {checked} state checks, "
        + ("ALL MATCH" if not bad else f"{len(bad)} MISMATCH"))
    return (not bad), bad, checked, mirror


# ======================================================================
# offline model of the seq_unit CSR slave — exercises the RUN protocol
# (START / poll / read-drain / error halt) with no board attached.
# ======================================================================
class _FakeSeqDev(Dev):
    """rtl/seq_unit.sv's AXI-Lite slave, in python, plus a scripted "run".

    Register semantics are the RTL's: START is ignored while busy, OUT_FIFO
    reads pop, STATUS packs {err_code, out_cnt, halted, err, busy}.  The run
    itself is scripted (halt pc, err_code, token list) so the host protocol —
    not the sequencer — is what gets tested.
    """

    def __init__(self, halt_pc, tokens, err_code=0, golden=None,
                 busy_polls=2):
        self.seq_ok, self.seq_why = True, "offline seq_unit model"
        self.chan, self.ddr_off, self.n_rd, self.n_wr = 0, 0, 0, 0
        self.log = lambda *a, **k: None
        self.ident = {"version": EXPECTED_SEQ_VERSION}
        self.regs = {S_BASE_LO: 0, S_BASE_HI: 0, S_LEN: 0, S_ENTRY: 0,
                     S_TCNT_SEQ: 0, L_SPTR: 0, L_XRFI: 0, L_LAYER: 0}
        self.xrf = [0] * SEQ_XRF_N
        self.g = golden or {}
        self._halt_pc, self._tok, self._err = halt_pc, list(tokens), err_code
        self._busy, self._halted, self._pc, self._fifo = False, False, 0, []
        self._of_ovf = False           # rung 4 S6: sticky until "reset"
        self._polls, self._busy_polls = 0, busy_polls

    # ---- the scripted run ----
    def _tick(self):
        if not self._busy:
            return
        self._polls += 1
        if self._polls >= self._busy_polls:
            self._busy, self._halted = False, True
            self._pc = self._halt_pc
            room = SEQ_OUT_DEPTH - len(self._fifo)
            if len(self._tok) > room:          # S6: pushes past 64 are DROPPED
                self._of_ovf = True
            self._fifo += self._tok[:max(0, room)]

    def rd(self, a):
        self.n_rd += 1
        if a == S_STATUS:
            self._tick()
            # rung 4 S6: out_cnt is 7 bits at [22:16] and of_ovf is bit 23
            return ((self._err << 24)
                    | (SEQ_ST_OF_OVF if self._of_ovf else 0)
                    | ((len(self._fifo) & SEQ_ST_OUTCNT_MASK) << 16)
                    | (0x4 if self._halted else 0) | (0x2 if self._err else 0)
                    | (0x1 if self._busy else 0))
        if a == S_CTRL:
            return ((0x4 if self._halted else 0) | (0x2 if self._err else 0)
                    | (0x1 if self._busy else 0))
        if a == S_PC:
            return self._pc
        if a == S_OUT_CNT:
            return len(self._fifo) & 0x7F
        if a == S_OUT_FIFO:
            if not self._fifo:
                return 0
            return SEQ_OUT_VALID | (self._fifo.pop(0) & SEQ_OUT_TOK_MASK)
        if a == S_IDENT:
            return SEQ_IDENT
        if a in (S_PERF_CYC, S_PERF_REC, S_PERF_AXW, S_PERF_AXR, S_PERF_FST):
            return {S_PERF_CYC: 181310224, S_PERF_REC: 60495,
                    S_PERF_AXW: 7724372, S_PERF_AXR: 17502428,
                    S_PERF_FST: 0}[a]
        if S_XRF0 <= a < S_XRF0 + 4 * SEQ_XRF_N:
            i = (a - S_XRF0) // 4
            return self.g.get("xrf", {}).get(i, self.xrf[i])
        if a == L_EOUT:
            return self.g.get("eout", 0)
        if a == L_AMAXI:
            return self.g.get("amax", (0, 0))[0]
        if a == L_AMAXV:
            return self.g.get("amax", (0, 0))[1]
        if a == L_TCNT:
            s = (self.regs[L_LAYER] >> 8) & 0x7
            lo, hi = self.g.get("tcnt", {}).get(s, (0, 0))
            return (hi << 16) | lo
        if a == L_XRFD:
            return self.g.get("xrf", {}).get(self.regs[L_XRFI], 0)
        return self.regs.get(a, 0)

    def wr(self, a, v):
        self.n_wr += 1
        v = int(v) & 0xFFFFFFFF
        if a == S_CTRL:
            if (v & SEQ_CTRL_START) and not self._busy:
                self._busy, self._halted, self._polls = True, False, 0
                self._pc = self.regs[S_ENTRY]
            if v & SEQ_CTRL_ABORT:
                self._busy, self._halted, self._err = False, True, 0x0C
            return
        if S_XRF0 <= a < S_XRF0 + 4 * SEQ_XRF_N:
            self.xrf[(a - S_XRF0) // 4] = v & 0x3FFFF
            return
        self.regs[a] = v

    def layer_read_scratch(self, addr, n):
        mem = self.g.get("mem", {})
        return np.array([mem.get(addr + i, 0) for i in range(n)],
                        dtype=np.int64)


# ======================================================================
# self-test (pure python; no board)
# ======================================================================
def _selftest(prefixes=None, log=print):
    """Unit-test the pure-python pieces against real gate artifacts."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cand = prefixes or [
        os.path.join(here, "tb", "scripts", "w3", "lay_s1.e"),
        os.path.join(here, "tb", "scripts", "w3", "tok2_s1.e"),
        os.path.join(here, "tb", "scripts", "w4", "model_v2_s1.e"),
        # rung 4 S4: the opt-in 4-chan stream, when it has been emitted
        os.path.join(here, "tb", "scripts", "w4", "model_v2_s1.e4"),
    ]
    cand = [p for p in cand if os.path.exists(p + ".seq.json")]
    if not cand:
        raise SystemExit("selftest: no .seq artifacts found — emit some with "
                         "SEQ_EMIT=<prefix> (tb/Makefile seq_chip_scripts)")
    npass = nfail = 0

    def check(name, cond, detail=""):
        nonlocal npass, nfail
        if cond:
            npass += 1
        else:
            nfail += 1
            log(f"    FAIL {name}: {detail}")
        return cond

    # ---- derive_base ----
    for p in cand:
        b = derive_base(p)
        check(f"derive_base({os.path.basename(p)})",
              os.path.exists(b + ".weights.json"),
              f"{b}.weights.json missing")

    for p in cand:
        log(f"  --- {p}")
        art = Artifacts(p)
        meta = art.meta
        # ---- 1. artifacts: hashes + validator + record count ----
        check("nrec == len(recs)", art.nrec == meta["nrec"])
        check("stream is 16B records",
              len(art.stream) == art.nrec * SEQ_REC_BYTES)
        check("halt_pc is the last record",
              art.halt_pc() == art.nrec - 1,
              f"halt_pc={art.halt_pc()} nrec={art.nrec}")

        # ---- 2. expected-token extraction ----
        toks = expected_tokens(meta)
        check("expect_tokens == metadata", toks == meta["expect_tokens"])
        check("one expected token per decode step",
              len(toks) == meta["steps"] - len(meta.get("prompt_fed", []))
              or len(toks) == meta["steps"],
              f"{len(toks)} tokens vs {meta['steps']} steps")
        # first_divergence contract
        check("first_divergence(equal) is None",
              first_divergence(toks, list(toks)) is None)
        if toks:
            m = list(toks)
            m[0] = m[0] + 1
            d = first_divergence(m, toks)
            check("first_divergence finds index 0",
                  d is not None and "token 0" in d, repr(d))
            d = first_divergence(toks[:-1], toks)
            check("first_divergence reports a short run",
                  d is not None and "common prefix" in d, repr(d))

        # ---- 3. address planning ----
        plan = plan_ddr(meta, len(art.stream), len(art.blob), chan=0)
        check("stream base is the hwmap one",
              plan["stream_base"] == SEQ_STREAM_BASE)
        check("data delta rebases the emitter blob",
              plan["data_delta"] == SEQ_DATA_BASE - meta["seq_data_base"])
        check("emb delta is 0 (emitter reads hwmap.EMB_BASE)",
              plan["emb_delta"] == 0, f"{plan['emb_delta']}")
        check("stream fits its window", len(art.stream) <= SEQ_STREAM_MAX)
        check("blob fits its window", len(art.blob) <= SEQ_DATA_MAX)
        check("stream/blob/weights/emb are disjoint",
              SEQ_STREAM_BASE + len(art.stream) <= SEQ_DATA_BASE
              and SEQ_DATA_BASE + len(art.blob) <= W_BASE)
        for c in (1, 2, 3):
            pc_ = plan_ddr(meta, len(art.stream), len(art.blob), chan=c) \
                if int(meta.get("chan", 0)) == c else None
            if pc_ is not None:
                check(f"chan {c} adds CH_STRIDE",
                      pc_["seq_base"] == c * CH_STRIDE + SEQ_STREAM_BASE)
        try:
            plan_ddr(meta, SEQ_STREAM_MAX + 1, len(art.blob), chan=0)
            check("oversized stream is rejected", False)
        except SeqError:
            check("oversized stream is rejected", True)
        try:
            plan_ddr(meta, len(art.stream), SEQ_DATA_MAX + 1, chan=0)
            check("oversized blob is rejected", False)
        except SeqError:
            check("oversized blob is rejected", True)

        # ---- 4. relocation ----
        recs2, rrep = relocate(art.recs, meta, plan, len(art.blob))
        check("relocation preserves the record count",
              len(recs2) == len(art.recs))
        nldc = sum(1 for r in art.recs if r.opcode == SF.EXT_LDC)
        nemb = sum(1 for r in art.recs if r.opcode == SF.OP_EMB)
        check("every LDC relocated", rrep["ldc"] == nldc,
              f"{rrep['ldc']} != {nldc}")
        check("every EMB visited", rrep["emb"] == nemb)
        moved = [(a, b) for a, b in zip(art.recs, recs2)
                 if a.to_bytes() != b.to_bytes()]
        check("only LDC/EMB records changed",
              all(a.opcode in (SF.EXT_LDC, SF.OP_EMB) for a, _b in moved))
        check("non-LDC/EMB records are byte-identical",
              all(a.to_bytes() == b.to_bytes()
                  for a, b in zip(art.recs, recs2)
                  if a.opcode not in (SF.EXT_LDC, SF.OP_EMB)))
        for a, b in zip(art.recs, recs2):
            if a.opcode == SF.EXT_LDC:
                if not check("LDC delta is exact",
                             _rec_addr64(b) - _rec_addr64(a)
                             == plan["data_delta"]):
                    break
                if not check("LDC flags/target/imm survive",
                             (a.flags, a.target, a.imm32)
                             == (b.flags, b.target, b.imm32)):
                    break
        offs = [_rec_addr64(r) - plan["data_base"]
                for r in recs2 if r.opcode == SF.EXT_LDC]
        check("every relocated LDC lands inside the uploaded blob",
              all(0 <= o < len(art.blob) for o in offs),
              f"min={min(offs) if offs else None} "
              f"max={max(offs) if offs else None} blob={len(art.blob)}")
        check("relocation is idempotent under a zero delta",
              relocate(recs2, dict(meta, seq_data_base=plan["data_base"],
                                   emb_base=plan["emb_base"]),
                       dict(plan, data_delta=0, emb_delta=0),
                       len(art.blob))[0][0].to_bytes()
              == recs2[0].to_bytes())
        # a corrupt blob address must be caught
        badrec = [SF.Rec(SF.EXT_LDC, imm32=8,
                         addr_lo=(meta["seq_data_base"] - 64) & 0xFFFFFFFF,
                         len_or_addr_hi=(meta["seq_data_base"] - 64) >> 32)]
        try:
            relocate(badrec, meta, plan, len(art.blob))
            check("out-of-blob LDC is rejected", False)
        except SeqError:
            check("out-of-blob LDC is rejected", True)

        # ---- 5. weight plan == sw/layer_test.py:plan_weights ----
        wbase_of, wtop = plan_weights(art.manifest, art.wdir)
        check_weight_plan(meta, wbase_of, art.manifest)
        check("weight pack ends below EMB_BASE", wtop < EMB_BASE)
        nmv = check_mvgo_targets(art.recs, wbase_of, art.manifest)
        check("every MVGO WBASE is row-aligned inside an image",
              nmv == sum(1 for r in art.recs if r.opcode == SF.OP_MVGO))
        try:
            check_weight_plan(dict(meta, weights=dict(
                (k, dict(v, base=int(v["base"]) + 64))
                for k, v in meta["weights"].items())), wbase_of, art.manifest)
            check("a shifted weight plan is rejected", False)
        except SeqError:
            check("a shifted weight plan is rejected", True)

        # ---- 5b. rung-1b 4-channel weight-split planning + addressing ----
        # Build a synthetic 4-chan meta from the real one; the fetch path
        # (stream/blob/emb) must be untouched and the weight images must be
        # row-split across chans 0..3 exactly as tok_meter.py:264-285 does.
        # `meta1` is a 1-chan view of this artifact's metadata: for a
        # committed 1-chan stream it IS the metadata, and for the rung-4
        # e4 stream it is the single-channel control case.
        meta1 = dict(meta, nch=1, chan=0)
        meta1.pop("weight_layout", None)
        p1 = plan_ddr(meta1, len(art.stream), len(art.blob), chan=0)
        meta4 = dict(meta, nch=4, chan=0)
        p4 = plan_ddr(meta4, len(art.stream), len(art.blob), chan=0)
        check("4-chan plan reports nch=4", p4["nch"] == 4)
        check("4-chan weight_chans are 0..3",
              p4["weight_chans"] == [0, 1, 2, 3])
        check("1-chan weight_chans is [fetch]", p1["weight_chans"] == [0])
        fetch_keys = ("seq_base", "data_base", "stream_base", "data_delta",
                      "emb_delta", "emb_base", "ddr_off")
        check("row-split leaves the FETCH path identical",
              all(p4[k] == p1[k] for k in fetch_keys),
              f"{[(k, p4[k], p1[k]) for k in fetch_keys if p4[k] != p1[k]]}")
        # a --chan that is not the emitter's fetch chan is rejected
        try:
            plan_ddr(meta4, len(art.stream), len(art.blob), chan=1)
            check("4-chan rejects a mismatched fetch --chan", False)
        except SeqError:
            check("4-chan rejects a mismatched fetch --chan", True)

        splits = plan_weight_split(art.manifest, wbase_of, 4, [0, 1, 2, 3])
        # (a) every image's quarters PARTITION its rows [0, nrows) once,
        #     land at the tok_meter address, and are row-aligned MVGO targets
        per_img = {}
        for s in splits:
            per_img.setdefault(s["wid"], []).append(s)
        cover_ok = addr_ok = align_ok = tok_ok = drop_ok = True
        for wid_s, mm in art.manifest.items():
            wid = int(wid_s)
            nrows, stride = int(mm["nrows"]), int(mm["stride"])
            wb = wbase_of[wid]
            pieces = sorted(per_img.get(wid, []), key=lambda s: s["r0"])
            # rows covered contiguously from 0 to nrows, each channel once
            row = 0
            for s in pieces:
                if s["r0"] != row or s["nrows_piece"] <= 0:
                    cover_ok = False
                row += s["nrows_piece"]
                if s["local_addr"] != wb + s["r0"] * stride:
                    addr_ok = False
                if (s["local_addr"] - wb) % stride:
                    align_ok = False
                # tok_meter.py:276 formula, recomputed independently
                r0_t, n_t = split_rows(nrows, 4)[s["chan"]]
                tok_abs = s["chan"] * CH_STRIDE + wb + r0_t * stride
                if s["abs_addr"] != tok_abs \
                        or (r0_t, n_t) != (s["r0"], s["nrows_piece"]):
                    tok_ok = False
                # local_addr must be a legal MVGO WBASE for this image
                if not (wb <= s["local_addr"] < wb + nrows * stride):
                    addr_ok = False
            if row != nrows:
                cover_ok = False
            # zero-row channels are dropped (nrows < 4 -> fewer than 4 pieces)
            if nrows < 4 and len(pieces) != nrows:
                drop_ok = False
            if nrows >= 4 and len(pieces) != 4:
                drop_ok = False
        check("4-chan split covers every row exactly once", cover_ok)
        check("4-chan quarters land at wbase+r0*stride", addr_ok)
        check("4-chan quarters are row-aligned MVGO targets", align_ok)
        check("4-chan addressing matches tok_meter:264-285", tok_ok)
        check("zero-row channels are dropped", drop_ok)
        # (b) total bytes == sum of full images; per-channel ranges disjoint
        tot = sum(s["byte_len"] for s in splits)
        full = sum(int(mm["nrows"]) * int(mm["stride"])
                   for mm in art.manifest.values())
        check("4-chan quarters sum to the whole weight footprint", tot == full,
              f"{tot} != {full}")
        for c in range(4):
            ranges = sorted((s["local_addr"], s["byte_len"])
                            for s in splits if s["chan"] == c)
            disj = all(ranges[i][0] + ranges[i][1] <= ranges[i + 1][0]
                       for i in range(len(ranges) - 1))
            check(f"chan {c} quarters are mutually disjoint", disj)
        check("weight pack fits inside one channel (bands disjoint)",
              wtop <= CH_STRIDE)
        # (c) nch=1 is byte-identical to the pre-1b whole-image write
        s1 = plan_weight_split(art.manifest, wbase_of, 1, [0])
        check("nch=1 gives one whole-image piece per image",
              len(s1) == len(art.manifest)
              and all(s["r0"] == 0 and s["byte_off"] == 0
                      and s["abs_addr"] == wbase_of[s["wid"]] for s in s1))
        # (d) synthetic edge cases: indivisible and nrows<nch
        synth = {"7": {"nrows": 5, "stride": 64},
                 "8": {"nrows": 3, "stride": 64}}
        sb = {7: 0x1000_0000, 8: 0x2000_0000}
        e5 = [s for s in plan_weight_split(synth, sb, 4, [0, 1, 2, 3])
              if s["wid"] == 7]
        check("nrows=5/4 -> row counts 2,1,1,1",
              [s["nrows_piece"] for s in e5] == [2, 1, 1, 1]
              and [s["r0"] for s in e5] == [0, 2, 3, 4])
        e3 = [s for s in plan_weight_split(synth, sb, 4, [0, 1, 2, 3])
              if s["wid"] == 8]
        check("nrows=3/4 -> only 3 channels used, chan 3 dropped",
              [s["chan"] for s in e3] == [0, 1, 2])

        # ---- 5c. rung-4 S4: the INTERLEAVED head placement ----------------
        # The emitter hands chunk j of the LM head to channel j % 4, so the
        # host must place that chunk (not a contiguous quarter) on that
        # channel.  Everything below is recomputed from seq_format so a
        # divergence between emitter and uploader is a FAILURE here, not a
        # wrong token on silicon.
        check("seq_format.split_rows == tok_meter.split_rows (the 1b pact)",
              all(SF.split_rows(n, k) == split_rows(n, k)
                  for n in (0, 1, 3, 5, 4096, 248320) for k in (1, 2, 3, 4)))
        head_wid = max(int(k) for k in art.manifest)
        m4 = dict(meta4, weight_layout={
            "nch": 4, "chunk_rows": SF.CHUNK_ROWS, "default": SF.LAYOUT_CONTIG,
            "by_wid": {str(head_wid): SF.LAYOUT_ILV},
            "ilv_wids": [head_wid]})
        si = plan_weight_split(art.manifest, wbase_of, 4, [0, 1, 2, 3], m4)
        hp = [s for s in si if s["wid"] == head_wid]
        others = [s for s in si if s["wid"] != head_wid]
        oc = [s for s in splits if s["wid"] != head_wid]
        check("S4 leaves every non-head image on the contiguous layout",
              others == oc)
        hrows = int(art.manifest[str(head_wid)]["nrows"])
        hstr = int(art.manifest[str(head_wid)]["stride"])
        check("the head is cut into <=CHUNK_ROWS chunks",
              len(hp) == -(-hrows // SF.CHUNK_ROWS)
              and all(s["nrows_piece"] <= SF.CHUNK_ROWS for s in hp),
              f"{len(hp)} pieces of {hrows} rows")
        check("chunk j lands on channel j % 4 (INTERLEAVED, not quarters)",
              [s["chan"] for s in hp] == [j % 4 for j in range(len(hp))],
              str([s["chan"] for s in hp][:8]))
        check("the interleaved chunks cover every head row exactly once",
              [s["r0"] for s in hp]
              == [j * SF.CHUNK_ROWS for j in range(len(hp))]
              and sum(s["nrows_piece"] for s in hp) == hrows)
        check("every interleaved chunk is a row-aligned MVGO WBASE",
              all(s["local_addr"] == wbase_of[head_wid] + s["r0"] * hstr
                  and (s["local_addr"] - wbase_of[head_wid]) % hstr == 0
                  for s in hp))
        check("interleaved pieces are disjoint per channel",
              all(_disjoint(sorted((s["local_addr"], s["byte_len"])
                                   for s in hp if s["chan"] == c))
                  for c in range(4)))
        check("S4 writes the whole head, no byte twice",
              sum(s["byte_len"] for s in hp) == hrows * hstr)
        check("the interleaved head is BALANCED across the 4 channels",
              max(sum(s["nrows_piece"] for s in hp if s["chan"] == c)
                  for c in range(4))
              - min(sum(s["nrows_piece"] for s in hp if s["chan"] == c)
                    for c in range(4)) <= SF.CHUNK_ROWS)
        check("a pre-rung-4 meta (no weight_layout) is still contiguous",
              plan_weight_split(art.manifest, wbase_of, 4, [0, 1, 2, 3],
                                meta1) == splits)
        check("layout_of defaults to contig for an unknown wid",
              layout_of(m4, 999) == SF.LAYOUT_CONTIG
              and layout_of(m4, head_wid) == SF.LAYOUT_ILV
              and layout_of({}, head_wid) == SF.LAYOUT_CONTIG)
        # the emitter's own map, recomputed: nch=1 never interleaves
        check("nch=1 collapses the interleave to one whole-image piece",
              SF.weight_pieces(hrows, 1, SF.LAYOUT_ILV) == [(0, 0, hrows)])

        # ---- 5d. THE property: every MVGO reads bytes the host wrote ------
        # For a real multi-channel stream, walk the ACTUAL records: each
        # MVGO names an engine channel and a [WBASE, WBASE+beats*64) span,
        # and that span must lie inside a piece plan_weight_split put on
        # THAT channel.  This is what makes the S4 interleave safe; it would
        # fail loudly if emitter and uploader ever disagreed by one chunk.
        if int(meta.get("nch", 1)) > 1:
            real = plan_weight_split(art.manifest, wbase_of,
                                     int(meta["nch"]),
                                     list(range(int(meta["nch"]))), meta)
            owned = {}
            for s in real:
                owned.setdefault(s["chan"], []).append(
                    (s["local_addr"], s["local_addr"] + s["byte_len"]))
            for c in owned:
                owned[c].sort()
            miss = []
            for i, r in enumerate(art.recs):
                if r.opcode != SF.OP_MVGO:
                    continue
                wb = ((int(r.len_or_addr_hi) & 0xFF) << 32) | int(r.addr_lo)
                end = wb + (int(r.len_or_addr_hi) >> 8) * 64
                if not any(lo <= wb and end <= hi
                           for (lo, hi) in owned.get(r.chan, ())):
                    miss.append((i, r.chan, wb, end))
            check(f"every MVGO of the {meta['nch']}-chan stream reads a span "
                  f"the host wrote to ITS channel",
                  not miss, f"{len(miss)} orphan MVGOs, first {miss[:2]}")
            check("...and the stream really does drive all 4 engines",
                  len({r.chan for r in art.recs
                       if r.opcode == SF.OP_MVGO}) == int(meta["nch"]))
            ilv_wids = set((meta.get("weight_layout") or {})
                           .get("ilv_wids", []))
            hits = {}
            for r in art.recs:
                if r.opcode != SF.OP_MVGO:
                    continue
                wb = ((int(r.len_or_addr_hi) & 0xFF) << 32) | int(r.addr_lo)
                for w in ilv_wids:
                    b = wbase_of[w]
                    mm = art.manifest[str(w)]
                    if b <= wb < b + int(mm["nrows"]) * int(mm["stride"]):
                        hits.setdefault(w, []).append(
                            (r.chan, (wb - b) // int(mm["stride"])))
            for w, hs in hits.items():
                per_step = sorted(set(hs))
                check(f"wid {w}: the head's chunks are INTERLEAVED "
                      f"(row/chunk_rows mod nch == channel)",
                      all(c == (row // SF.CHUNK_ROWS) % int(meta["nch"])
                          for (c, row) in per_step),
                      str(per_step[:6]))
                check(f"wid {w}: the head's rows are covered exactly once",
                      sorted(row for (_c, row) in per_step)
                      == [j * SF.CHUNK_ROWS
                          for j in range(len(per_step))],
                      f"{len(per_step)} distinct chunks")

        # ---- 6. disasm window ----
        w = disasm_window(art.recs, art.halt_pc(), n_before=4)
        check("disasm_window marks the PC", "<<< PC" in w)

        # ---- 7. .chip golden parser, when one exists ----
        gp = p + ".chip"
        if os.path.exists(gp):
            g = parse_chip_golden(gp)
            check("golden NREC matches", g["nrec"] == art.nrec)
            check("golden PC is the HALT record", g["pc"] == art.halt_pc())
            check("golden tokens == expect_tokens", g["tok"] == toks,
                  f"{g['tok']} vs {toks}")
            check("golden BASES are the emitter's",
                  g["bases"][:3] == [meta["seq_stream_base"],
                                     meta["seq_data_base"], meta["emb_base"]])
            check("golden covers the scratchpad minus staging",
                  len(g["mem"]) == SCRATCH_WORDS
                  - sum(b - a for a, b in meta.get("staging_words", [])),
                  f"{len(g['mem'])} words")
        # ---- 8. the RUN protocol, against an offline seq_unit CSR model ----
        golden = parse_chip_golden(gp) if os.path.exists(gp) else None
        fake = _FakeSeqDev(art.halt_pc(), toks, golden=golden)
        run = seq_start_and_poll(fake, art, plan, timeout=5.0,
                                 log=lambda *a: None)
        check("run halts at the HALT record", run["pc"] == art.halt_pc())
        check("run reports no error", run["status"]["err_code"] == 0)
        check("OUT FIFO drained in order", run["tokens"] == toks,
              f"{run['tokens']} vs {toks}")
        check("BASE_LO was written with the planned base",
              fake.regs[S_BASE_LO] == (plan["seq_base"] & 0xFFFFFFFF))
        check("LEN was written with nrec", fake.regs[S_LEN] == art.nrec)
        check("XRF was zeroed before START", fake.xrf == [0] * SEQ_XRF_N)
        check("tokens match the metadata",
              first_divergence(run["tokens"], toks) is None)
        if golden:
            gok, gbad, gchk, _mir = verify_chip_golden(
                fake, art, run, golden, log=lambda *a: None)
            check("golden state check passes on matching state", gok,
                  "; ".join(gbad[:4]))
            check("golden state check is not vacuous",
                  gchk > len(golden["mem"]))
            g2 = dict(golden, eout=(golden["eout"] + 1) & 0xF)
            gok2, _b, _c, _m = verify_chip_golden(
                _FakeSeqDev(art.halt_pc(), toks, golden=golden), art, run, g2,
                log=lambda *a: None)
            check("golden state check catches a bad EOUT", not gok2)
        # error halt: the failure report must name the code and mark the PC
        bad_pc = min(len(art.recs) - 1, max(0, art.halt_pc() // 2))
        fake_e = _FakeSeqDev(bad_pc, [], err_code=0x10)
        run_e = seq_start_and_poll(fake_e, art, plan, timeout=5.0,
                                   log=lambda *a: None)
        fr = failure_report(art, run_e)
        check("failure report names the err_code",
              "layer_chan err_op" in fr and "0x10" in fr, fr[:200])
        check("failure report marks the failing record", "<<< PC" in fr)
        check("failure report shows the last records issued",
              fr.count("\n") >= 14, f"{fr.count(chr(10))} lines")
        # token divergence path
        if toks:
            fake_t = _FakeSeqDev(art.halt_pc(), toks[:-1] + [toks[-1] + 1])
            run_t = seq_start_and_poll(fake_t, art, plan, timeout=5.0,
                                       log=lambda *a: None)
            check("a wrong last token is detected",
                  first_divergence(run_t["tokens"], toks) is not None)
        # a busy sequencer is refused, not stomped on
        fake_b = _FakeSeqDev(art.halt_pc(), toks)
        fake_b._busy = True
        try:
            seq_start_and_poll(fake_b, art, plan, timeout=5.0,
                               log=lambda *a: None)
            check("a busy sequencer is refused", False)
        except SeqError:
            check("a busy sequencer is refused", True)
        # and the SEQ CSRs are refused outright when the gate said no
        blocked = _FakeSeqDev(art.halt_pc(), toks)
        blocked.seq_ok, blocked.seq_why = False, "no build_029"
        try:
            blocked.seq_rd(S_STATUS)
            check("a closed SEQ gate blocks CSR access", False)
        except SystemExit:
            check("a closed SEQ gate blocks CSR access", True)

        log(f"      {art.nrec} records, {len(art.blob)} B blob, "
            f"{rrep['ldc']} LDC ({rrep['ldc_indirected']} indirected), "
            f"{nmv} MVGO, {len(toks)} expected tokens")

    log(f"  seq_run selftest: {npass} passed, {nfail} failed")
    return nfail == 0


# ======================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", help="<prefix>.seq / .seqdata.bin / .seq.json")
    ap.add_argument("--base", default=None,
                    help="generator-artifact prefix (.weights.json, _w*.bin, "
                         ".emb.bin); default = --prefix minus its last "
                         "dotted component")
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0,
                    help="DDR FETCH channel (stream/blob/emb); must match the "
                         "emitter's chan")
    ap.add_argument("--four-chan", action="store_true",
                    help="require a row-split (meta nch>1) stream: weights "
                         "are split across DDR channels 0..nch-1 and each "
                         "quarter is readback-verified where its matvec_chan "
                         "reads it.  The mode is otherwise auto-detected from "
                         "meta['nch']; this flag just asserts it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan + relocate + upload + readback-verify, and "
                         "NOTHING ELSE — no access at all to the SEQ CSR "
                         "window, so this is the mode that is safe on a "
                         "bitstream without seq_0")
    ap.add_argument("--skip-weights", action="store_true",
                    help="weights + embedding are already resident")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the DDR readback comparison")
    ap.add_argument("--no-xrf-init", action="store_true",
                    help="do not zero XRF[0..7] before START")
    ap.add_argument("--entry", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--chip", default=None,
                    help="post-halt golden from tb/scripts/"
                         "gen_seq_chip_vectors.py (default <prefix>.chip)")
    ap.add_argument("--no-chip", action="store_true")
    ap.add_argument("--dump-scratch", default=None,
                    help="save the post-halt 16K scratchpad to a .npy")
    ap.add_argument("--out", default=None, help="JSON report path")
    ap.add_argument("--selftest", action="store_true",
                    help="unit-test the pure-python pieces (no board)")
    args = ap.parse_args()

    if args.selftest:
        print("seq_run selftest (pure python, no board):")
        raise SystemExit(0 if _selftest() else 1)
    if not args.prefix:
        ap.error("--prefix is required (or --selftest)")

    rep = {
        "test": "seq_run",
        "prefix": args.prefix,
        "dry_run": bool(args.dry_run),
        "git": subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=SW_DIR).stdout.strip(),
        "pass": True,
    }

    # ---------------- artifacts ----------------
    art = Artifacts(args.prefix, base=args.base)
    m = art.meta
    print(f"--- SEQ stream: {args.prefix}")
    print(f"  artifacts base   {art.base}")
    print(f"  stream           {art.nrec} records, {len(art.stream)} B "
          f"(sha256 {m['stream_sha256'][:16]}) VALIDATED")
    print(f"  seqdata          {len(art.blob)} B "
          f"(sha256 {m['seqdata_sha256'][:16]})")
    loop_note = ("structurally safe" if m.get("loop_structurally_safe")
                 else m["loop_note"])
    print(f"  profile          {m['profile']}  dyn_ka={m.get('dyn_ka')}  "
          f"loop {m['loop_steps']} steps ({loop_note})")
    print(f"  opcodes          {m['opcode_histogram']}")
    print(f"  expected tokens  {expected_tokens(m)}")
    rep["meta"] = {k: m[k] for k in ("nrec", "stream_bytes", "stream_sha256",
                                     "seqdata_bytes", "seqdata_sha256",
                                     "profile", "steps", "loop_steps",
                                     "loop_structurally_safe",
                                     "expect_tokens")}

    # ---------------- mode (1-chan vs row-split) ----------------
    nch = int(m.get("nch", 1))
    if args.four_chan and nch <= 1:
        ap.error(f"--four-chan given but the stream is single-channel "
                 f"(meta nch={nch}); regenerate with the 4-chan emitter "
                 f"(ref/seq_format SEQ_NCH=4)")
    if nch > 1:
        print(f"  mode             {nch}-CHANNEL row-split "
              f"(weights over DDR chans {list(range(nch))}, fetch on "
              f"chan {m.get('chan', 0)})"
              + ("" if args.four_chan else "  [auto-detected from meta nch]"))
    else:
        print(f"  mode             single-channel (engine chan "
              f"{m.get('chan', 0)})")

    # ---------------- plan + relocate ----------------
    plan = plan_ddr(m, len(art.stream), len(art.blob), chan=args.chan)
    recs, rrep = relocate(art.recs, m, plan, len(art.blob))
    print(f"--- DDR plan (fetch channel {args.chan}, host offset "
          f"{plan['ddr_off']:#x}, nch={plan['nch']})")
    print(f"  stream    {plan['stream_base']:#x} .. "
          f"{plan['stream_base'] + len(art.stream):#x}  "
          f"(window {SEQ_STREAM_MAX >> 20} MiB)")
    print(f"  seqdata   {plan['data_base']:#x} .. "
          f"{plan['data_base'] + len(art.blob):#x}  "
          f"(window {SEQ_DATA_MAX >> 20} MiB)")
    print(f"  weights   {W_BASE:#x} ..            (plan_weights, "
          f"{len(art.manifest)} images, chans {plan['weight_chans']})")
    print(f"  embedding {plan['emb_base']:#x}  (fetch chan {args.chan})")
    print(f"  RELOCATION: {rrep['ldc']} LDC records "
          f"({rrep['ldc_indirected']} XRF-indirected) rebased by "
          f"{rrep['data_delta']:+#x} "
          f"(emitter {int(m['seq_data_base']):#x} -> "
          f"{plan['data_base']:#x}); {rrep['emb']} EMB records checked, "
          f"delta {rrep['emb_delta']:+#x}")
    rep["plan"] = {k: (hex(v) if isinstance(v, int) else v)
                   for k, v in plan.items()}
    rep["relocation"] = rrep

    # ---------------- board ----------------
    dev = Dev(args.dev, chan=args.chan, allow_seq=not args.dry_run)
    print(f"--- board: MAGIC={dev.ident['magic']:#010x} "
          f"VERSION={dev.ident['version']:#010x} "
          f"CALIB={dev.ident['calib']:#x}  "
          f"SEQ={'READY' if dev.seq_ok else 'REFUSED'}")
    if not dev.seq_ok:
        print(f"  SEQ CSRs untouched: {dev.seq_why}")
    rep["ident"] = {k: (hex(v) if isinstance(v, int) else v)
                    for k, v in dev.ident.items()}
    rep["seq_ok"], rep["seq_why"] = dev.seq_ok, dev.seq_why

    wbase_of, _wtop = plan_weights(art.manifest, art.wdir)
    check_weight_plan(m, wbase_of, art.manifest)
    nmv = check_mvgo_targets(art.recs, wbase_of, art.manifest)
    print(f"  weight plan: {len(wbase_of)} images match the stream's MVGO "
          f"plan; {nmv} MVGO WBASEs row-aligned inside them")

    # ---------------- upload ----------------
    print("--- upload")
    urep, wbase_of, _stream = upload(dev, art, plan, recs,
                                     do_weights=not args.skip_weights,
                                     verify=not args.no_verify)
    print(f"  {urep['bytes'] / 2**20:.0f} MiB written, "
          f"{urep['verified_bytes'] / 2**20:.0f} MiB read back and compared, "
          f"{urep['seconds']}s")
    rep["upload"] = urep

    if args.dry_run:
        print("--- DRY RUN COMPLETE: DDR images uploaded and readback-"
              "verified; the SEQ CSR window was never accessed.")
        rep["pass"] = True
        _emit(rep, args.out)
        raise SystemExit(0)

    # ---------------- run ----------------
    print("--- run")
    run = seq_start_and_poll(dev, art, plan, timeout=args.timeout,
                             entry=args.entry,
                             init_xrf=not args.no_xrf_init)
    st = run["status"]
    print(f"  halted at pc={run['pc']}/{art.nrec} in {run['wall_s']}s wall / "
          f"{run['device_ms']} ms device")
    print(f"  STATUS={st['raw']:#010x} err={st['err']} "
          f"err_code={st['err_code']:#04x} ({seq_err_name(st['err_code'])})")
    print(f"  perf: {run['perf']}")
    print(f"  tokens: {run['tokens']}")
    rep["run"] = {k: v for k, v in run.items() if k != "status"}
    rep["run"]["status"] = {k: v for k, v in st.items()}
    if run.get("warn_fifo_full"):
        print("  WARNING: " + run["warn_fifo_full"])

    ok = True
    if st["err"] or st["err_code"]:
        print(failure_report(art, run))
        rep["failure"] = failure_report(art, run)
        ok = False
    elif run["pc"] != art.halt_pc():
        print(f"  PC {run['pc']} is not the HALT record {art.halt_pc()}")
        rep["failure"] = f"pc {run['pc']} != halt {art.halt_pc()}"
        ok = False

    # ---------------- verify ----------------
    want = expected_tokens(m)
    d = first_divergence(run["tokens"], want)
    if d is None:
        print(f"  TOKENS   IDENTICAL to the .seq.json ({len(want)} tokens)")
    else:
        print("  TOKENS   MISMATCH\n    " + d.replace("\n", "\n    "))
        rep["token_divergence"] = d
        ok = False
    rep["tokens_ok"] = d is None

    gp = args.chip or (art.prefix + ".chip")
    if not args.no_chip and os.path.exists(gp) and st["halted"]:
        print(f"--- post-halt state vs {gp}")
        gok, bad, nchk, mirror = verify_chip_golden(dev, art, run,
                                                    parse_chip_golden(gp))
        for line in bad[:12]:
            print("    ! " + line)
        rep["golden"] = {"path": gp, "checks": nchk, "pass": gok,
                         "mismatches": bad[:32],
                         "layer_xrf_mirror": {str(k): hex(v)
                                              for k, v in mirror.items()}}
        ok = ok and gok

    if args.dump_scratch:
        scr = dev.layer_read_scratch(0, SCRATCH_WORDS).astype(np.uint16)
        np.save(args.dump_scratch, scr)
        print(f"  scratch dump -> {args.dump_scratch}")

    rep["pass"] = ok
    print("SEQ RUN: " + ("PASS" if ok else "FAIL"))
    _emit(rep, args.out)
    raise SystemExit(0 if ok else 1)


def _emit(rep, path):
    if path:
        with open(path, "w") as f:
            json.dump(rep, f, indent=1, default=str)
        print(f"report -> {path}")


if __name__ == "__main__":
    main()
