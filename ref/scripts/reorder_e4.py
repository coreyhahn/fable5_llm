#!/usr/bin/env python3
"""reorder_e4.py — Task SV1: the emitter-side S1 schedule, as a post-pass
over an emitted `.e4` stream (fence-at-use + dependency-safe reorder +
redundant-MOVX elision; OV1_DEPENDENCY_CENSUS.md §6.1 items 1-3).

    FABLE5_MODEL=9b python ref/scripts/reorder_e4.py --selftest
    FABLE5_MODEL=9b python ref/scripts/reorder_e4.py \
        --in tb/scripts/w9/model_9b_s1.e4 --out tb/scripts/w9/model_9b_s1_reordB.e4 \
        --form B [--stats]

THE MODEL IS OV1'S, IMPORTED — NOT PORTED.  The read/write sets
(`rw_cmd`, `named_cmd`, `build_nodes`), the dependency edges
(`build_edges`, both forms), the list scheduler (`schedule`, the three
global-FENCE issue rules of `run_sched`) and the independent post-check
(`postcheck`) are `evidence/qwen9b/ov/ov_census.py`'s own functions, called
here unchanged, so this pass cannot drift from the model OV1 predicted with.
The scheduler needs per-record windows.  S1P: by DEFAULT (`--cost static`)
they come from `ref/seq_cost.py`, priced from the record fields alone (E1's
per-key ALU/VN costs + per-class formulas fitted on BN1's CSV), so ANY
stream can be reordered.  `--cost csv` keeps SV1's path: BN1's timeline CSV
of `model_9b_s1` (sha-checked by `ov_census.load_csv`), mapped onto each
segment of the target stream through a segment whose record SKELETON
(opcode, channel, CSR target per record) is identical — the path the SV1
pins (and chat_seq's `--reorder A`) were generated with.

WHAT THE PASS DOES, per decode segment (one EMB .. the next EMB; the loop
body ends at its JMP):
  1. OV1's node list + edges for the chosen form, redundant MOVX elided;
  2. the best of OV1's three global-FENCE issue rules (the S1 row of
     `run_sched`), i.e. the schedule OV1's S1 number is the makespan of;
  3. emits the live records in that schedule's order, each CMD preceded by
     the ARG CSRWRs that rode with it, the JMP last, and a FENCE exactly
     before each record that needs a stream that is issued but not yet
     fenced (on the shipped RTL a FENCE drains EVERY channel,
     rtl/seq_unit.sv:821-824, so fence-at-use can only DEFER a fence);
  4. replays the emitted order through the same one-lane/global-FENCE
     timing and runs OV1's `postcheck` on THAT replay (every dependency
     edge, no MOVX on a streaming XWIN, no MVGO on a streaming engine, no
     MOVY before its stream, no lane overlap);
  5. re-derives the ARG CSR values each CMD sees and asserts they are the
     program-order values.
Then, over the WHOLE output stream, the hazard ASSERT the OV1 review made
binding (I1): no MOVX, MVGO or MOVY on a channel with a pending (issued,
unfenced) stream, and nothing pending at the loop's JMP.  The live-state
checkpoints the SEQ gate samples are carried to a position where every
scratch word of their region has the same last writer as in program order.
The output is written with seq_format's own packer and validator; the
`.seqdata.bin` is copied byte for byte (the data blob does not move).

SR4 — `--rtl {r0,r1}` (the sequencer RTL round, SEQ_ISA v2.3 §B17.1).  r0
(the default) is everything above, byte for byte.  r1 emits for the FENCE
channel mask: step 2 is OV1's per-channel-fence schedule (the R1 row of
`run_sched`: fence "perchan", bottom-level priority), step 3 puts a FENCE
whose target[3:0] is EXACTLY the channels of the unfenced streams the next
record's stream-edges need (at the JMP, every pending channel) and clears
only those, step 4's replay drains only the masked channels, and the hazard
assert is mask-aware (a channel outside the mask stays pending).  The output
validates at caps {"R1"} and must be REFUSED at the empty set (build_041/
042); the manifest records "seq_isa": "2.3" and "caps": ["R1"]
(informational — admission is the device's SEQ_CAPS).  The input must be an
r0 stream (OV1's FENCE groups assume the global drain).

SR11b — `--rtl r2` (SEQ_ISA v2.3 §B17.2, XWIN/RES double banking).  Step 2
schedules with the census's DEPTH-2 buffers (ov_census.build_edges with
xdepth = rdepth = 2: a K <= 6144 vector alternates XWIN banks, a <= 2048-row
chunk alternates RES banks, larger ones span both) under the per-channel
fence (the R1+R2 row of run_sched), and step 3 EMITS THE BANK THE MODEL
ASSIGNED: MOVX target = 1536 * bank (0 on a span), MVGO SHAPE bit 29 =
XBANK and bit 30 = RBANK (0 on a span), MOVY target[15:4] = 2048 * the RES
bank it drains (the census records it per MOVY).  Elision stays the
census's (same channel, same source, source unwritten since) and the
MVGO of an elided MOVX reads the bank the SURVIVING copy sits in (the
census's xsel is not advanced by an elided MOVX).  The FENCEs are r1's
(masked, per record's stream-edges).  The hazard assert is RANGE-aware,
the model's rule (ref/seq_model.py running ranges): a MVGO on a channel
with ANY pending stream is refused; a MOVX only if its XWIN word range
overlaps the pending stream's x range [1536*XBANK, +32*ng); a MOVY only if
its row range overlaps the pending RES range [2048*RBANK, +nrows) — with
every bank field zero that is the per-channel rule exactly.  The output
validates at caps {"R1","R2"} and must be REFUSED at {"R1"} and at the
empty set; the manifest records "caps": ["R1","R2"].  The input must carry
no bank field (the census assigns banks from program order).

SR11b — `predict()`: the CORRECTED cost convention (ref/seq_cost.py
FENCE_REC / TAIL1 / CMD_RESID_FRAC, fitted on SR5b's measured R1 run) prices
an emitted order: every FENCE record 23 cycles, a waiting FENCE ends the
drained class's single-channel tail after its stream, plus the inherited
CMD residual.  It changes PREDICTIONS only: the scheduler and `replay()`
keep the census's convention, so no r0/r1 schedule or output moves.  At
r2 each segment reports both (replay_mk: the census convention, beside
OV1's R1+R2 row; pred_mk: the corrected prediction).
"""
import argparse
import collections
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "ref"))
sys.path.insert(0, os.path.join(REPO, "evidence", "qwen9b", "ov"))

import seq_format as SF                     # noqa: E402
import gen_layer_script as GLS              # noqa: E402
import ov_census as OC                      # noqa: E402  (OV1's model)
import seq_cost as SC                       # noqa: E402  (S1P: static costs)

FORM_CHAIN = {"A": "order", "B": "free"}
# run_sched's global-FENCE heuristic search (ov_census.py, run_sched `heur`)
HEUR = (("pc/weak", {"prio": "pc", "guard": "weak"}),
        ("bl/weak", {"prio": "bl", "guard": "weak"}),
        ("bl/strong", {"prio": "bl", "guard": "strong"}))
ARG_CSRS = (SF.CSR_L_ARG0, SF.CSR_L_ARG1, SF.CSR_L_ARG2)
TEMPLATE = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1.e4")
# S1P: where the per-record windows come from.  "static" (the default) =
# ref/seq_cost.py, priced from the record fields (any stream); "csv" = the
# SV1 path, BN1's timeline CSV of model_9b_s1 mapped by segment skeleton
# (the stream must match a template segment; kept to reproduce SV1's pins).
COSTS = ("static", "csv")
# SR4: the RTL level the pass emits for.  r0 = the shipped RTL (a FENCE
# drains every channel; OV1's S1 schedule; output byte-identical to the
# pre-SR4 pass); r1 = SEQ_ISA v2.3 B17.1's FENCE channel mask (OV1's
# per-channel-fence schedule, the R1 row of ov_census.run_sched; every
# FENCE carries exactly the channels the next record needs drained); r2 =
# SR11b, SEQ_ISA v2.3 B17.2's XWIN/RES banks on top of r1 (the census's
# depth-2 buffers, the R1+R2 row; the bank the model assigned is emitted).
RTLS = ("r0", "r1", "r2")
# the R1 row of ov_census.run_sched: per-channel fence, bottom-level priority
HEUR_R1 = (("bl", {"prio": "bl"}),)
CAPS_OF = {"r0": frozenset(), "r1": frozenset({"R1"}),
           "r2": frozenset({"R1", "R2"})}
# XWIN / RES buffers per channel the census schedules with (build_edges'
# xdepth / rdepth): 2 = the R2 banks
DEPTH = {"r0": 1, "r1": 1, "r2": 2}


class HazardError(AssertionError):
    pass


class ReorderError(AssertionError):
    """Fix round 1: every structural / safety check of this pass raises
    EXPLICITLY, so none of them is stripped by `python -O`."""


def need(cond, msg):
    if not cond:
        raise ReorderError(msg)


# ======================================================================
# stream structure
# ======================================================================
def segments(recs):
    """-> (prologue_end, [(lo, hi_incl, is_body)], halt_index).
    Segments are EMB-delimited decode steps; the loop body is the segment
    the JMP (flags JMP_TCNT) closes, and its JMP is its last record."""
    halt = [i for i, r in enumerate(recs) if r.opcode == SF.OP_HALT]
    need(len(halt) == 1 and halt[0] == len(recs) - 1, "one final HALT")
    embs = [i for i, r in enumerate(recs) if r.opcode == SF.OP_EMB]
    jmps = [i for i, r in enumerate(recs) if r.opcode == SF.OP_JMP]
    need(len(jmps) <= 1, f"{len(jmps)} JMP records")
    if not embs:
        return 0, [(0, halt[0] - 1, False)], halt[0]
    segs = []
    for k, lo in enumerate(embs):
        hi = (embs[k + 1] - 1) if k + 1 < len(embs) else halt[0] - 1
        segs.append((lo, hi, False))
    if jmps:
        j = jmps[0]
        need(recs[j].flags & SF.JMP_TCNT and recs[j].imm32 == embs[-1]
             and j == halt[0] - 1, "the JMP must close the last segment")
        lo, hi, _ = segs[-1]
        segs[-1] = (lo, hi, True)
    return embs[0], segs, halt[0]


def skeleton(recs, lo, hi):
    out = []
    for r in recs[lo:hi + 1]:
        o = r.opcode
        if o in (SF.OP_MOVX, SF.OP_MOVY, SF.OP_MVGO):
            out.append((o, r.chan))
        elif o == SF.OP_CSRWR:
            out.append((o, r.target))
        elif o == SF.OP_CMD:
            out.append((o, r.imm32 & 0xFF))
        else:
            out.append((o,))
    return hashlib.sha256(repr(out).encode()).hexdigest()


# ======================================================================
# the hazard ASSERT (OV1 review I1) — over a whole record stream
# ======================================================================
def _overlap(a0, a1, b0, b1):
    """Half-open ranges share an element; an EMPTY access range counts as
    overlapping — ref/seq_model._overlap's rule, so a zero-length MOVX/MOVY
    on a pending channel is refused exactly as before R2."""
    return a1 <= a0 or (a0 < b1 and b0 < a1)


def _stream_ranges(r, shape_isa=None):
    """SR11b: (x word lo, hi, RES row lo, hi) a no-wait MVGO keeps reading /
    writing until its FENCE — ref/seq_model.SeqExec._mvgo's running range.
    The SHAPE layout is this tree's (G3.3: ng[28:22], nrows[21:6], XBANK
    bit 29, RBANK bit 30); a caller holding a frozen isa=1 stream (bit 29 =
    w8) states shape_isa=1 and gets no banks."""
    shape = r.imm32
    ng = (shape >> 22) & 0x7F
    nrows = (shape >> 6) & 0xFFFF
    xb = rb = 0
    if shape_isa != 1:
        xb = (shape >> 29) & 1
        rb = (shape >> 30) & 1
    x0 = SF.XBANK_WORD * xb
    r0 = SF.RBANK_ROW * rb
    return (x0, x0 + SF.XWIN_LINE_WORDS * max(ng, 1),
            r0, r0 + max(nrows, 1))


def assert_no_pending_hazard(recs, where="stream", shape_isa=None):
    """Walk the stream in static order (the loop body is entered clean and
    must leave clean, so one static walk covers every iteration).  Raises
    HazardError naming the record if a MOVX, MVGO or MOVY lands on a
    channel whose no-wait stream is issued and not yet fenced, or if a
    stream is still pending at the JMP or the HALT.  SR4: mask-aware — a
    FENCE drains only the channels of its target[3:0] (0 = all).  SR11b:
    RANGE-aware (SEQ_ISA v2.3 B17.2, the model's running ranges) — a MVGO
    is refused on a channel with ANY pending stream; a MOVX only if its
    XWIN words [target[11:0], +ceil(len/4)) overlap the pending stream's x
    range; a MOVY only if its RES rows [target[15:4], +len) overlap the
    pending RES range.  With every bank field zero the ranges always
    overlap: the per-channel rule, unchanged."""
    pend = {}
    n = {"MOVX": 0, "MVGO": 0, "MOVY": 0, "FENCE": 0}
    for i, r in enumerate(recs):
        o = r.opcode
        if o in (SF.OP_MOVX, SF.OP_MVGO, SF.OP_MOVY):
            c = _r3_chan(r, i, pend, where)       # R3-5: chan 0xF by name
            name = SF.OP_NAME[o]
            n[name] += 1
            if c in pend:
                p, rg = pend[c]
                if o == SF.OP_MOVX:
                    w0 = r.target & SF.MOVX_WORD_MASK
                    a = (w0, w0 + SF.movx_words(r.len_or_addr_hi & 0xFFFFFF))
                    hit = _overlap(a[0], a[1], rg[0], rg[1])
                elif o == SF.OP_MOVY:
                    y0 = r.target >> 4
                    a = (y0, y0 + (r.len_or_addr_hi & 0xFFFFFF))
                    hit = _overlap(a[0], a[1], rg[2], rg[3])
                else:
                    a, hit = None, True
                if hit:
                    raise HazardError(
                        f"{where}: record {i} {name} on mv{c} while the "
                        f"no-wait MVGO at record {p} is still pending (no "
                        f"FENCE between)"
                        + ("" if a is None else
                           f"; its range {a} overlaps the pending "
                           f"{'x words' if o == SF.OP_MOVX else 'RES rows'}"
                           f" {rg[:2] if o == SF.OP_MOVX else rg[2:]}"))
            if o == SF.OP_MVGO:
                if not (r.target & SF.MVGO_NOWAIT):
                    raise HazardError(f"{where}: blocking MVGO at {i}")
                pend[c] = (i, _stream_ranges(r, shape_isa))
        elif o == SF.OP_FENCE:
            n["FENCE"] += 1
            # SR4 (SEQ_ISA v2.3 B17.1): target[3:0] is the channel mask,
            # bit c = channel c, mask 0 = all four.  Only the masked
            # channels are drained; a pending channel outside the mask
            # STAYS pending, so its next MOVX/MVGO/MOVY is refused above.
            fm = r.target & 0xF
            if fm == 0:
                pend = {}
            else:
                for c in range(4):
                    if (fm >> c) & 1:
                        pend.pop(c, None)
        elif o in (SF.OP_JMP, SF.OP_HALT):
            if pend:
                raise HazardError(
                    f"{where}: record {i} {SF.OP_NAME[o]} with streams "
                    f"still pending {sorted((c, p[0]) for c, p in pend.items())}")
    return n


# ======================================================================
# one segment
# ======================================================================
def schedule_segment(recs, lo, hi, rows, form, rtl="r0"):
    """OV1's S1 schedule of records lo..hi (r0), or its R1 schedule (r1:
    per-channel fence, the R1 row of ov_census.run_sched), or its R1+R2
    schedule (r2, SR11b: r1 on the depth-2 XWIN/RES buffers).  `rows[pc]` =
    the measured (opcode, cyc0, dur, cls16) window of static record pc."""
    nodes = OC.build_nodes(recs, lo, hi, rows)
    groups, leak = OC.stream_durations(nodes, rows)
    d = DEPTH[rtl]
    nred, bc = OC.build_edges(nodes, True, d, d, FORM_CHAIN[form]), _r3_merge(nodes, rtl)
    best = None
    trials = []
    for hname, h in (HEUR if rtl == "r0" else HEUR_R1):
        cfg = {"lanes": 1, "fence": "global" if rtl == "r0" else "perchan",
               "elide": True, "hoist_guard": True}
        cfg.update(h)
        mk, st, fi, se, stt = OC.schedule(nodes, groups, cfg)
        trials.append((hname, mk, stt["post"]))
        if best is None or mk < best[1]:
            best = (hname, mk, st, fi, se, stt)
    hname, mk, st, fi, se, stt = best
    live = [n.kind not in ("fence", "arg") and not n.redundant
            for n in nodes]
    return {"nodes": nodes, "groups": groups, "leak": leak, "nred": nred,
            "live": live, "rule": hname, "mk": mk, "start": st, "fin": fi,
            "send": se, "post": stt["post"], "trials": trials,
            "sched_fences": stt["fences"],
            "orig_win": sum(n.dur for n in nodes), "bcast": bc}


def is_fence(x):
    """An emitted-order item that is a FENCE: 'FENCE' (r0, drains all) or
    ('FENCE', mask) (r1, SEQ_ISA v2.3 B17.1)."""
    return x == "FENCE" or (isinstance(x, tuple) and x[0] == "FENCE")


def fence_mask(x):
    """The FENCE item's target[3:0]: 0 (= all four) for an r0 'FENCE'."""
    return 0 if x == "FENCE" else x[1]


def order_and_fences(S, rtl="r0"):
    """The emitted order: the schedule's live records by start time (ties,
    which only zero-length records can make, by program order — every edge
    points forward in program order, so that is a topological order), the
    JMP last; a FENCE before each record with a stream-edge to an issued,
    unfenced MVGO.  Returns [node index or 'FENCE'].

    r1 (SR4): the FENCE is ('FENCE', mask) and its mask is EXACTLY the
    channels of the issued, unfenced MVGOs that record's stream-edges need
    (at the JMP: every channel still pending); it clears only those.  An
    MVGO on a channel with an unfenced stream always carries a stream-edge
    to it (ov_census.build_edges: one stream per engine), so at most one
    stream per channel is ever pending here.  r2 (SR11b) is the same: a
    MOVX into the OTHER XWIN bank, or a MOVY of the other RES bank, carries
    no stream-edge to the running stream, so it needs no FENCE."""
    nodes, live, st = S["nodes"], S["live"], S["start"]
    idx = [i for i in range(len(nodes)) if live[i]]
    jmp = [i for i in idx if nodes[i].op == SF.OP_JMP]
    idx = [i for i in idx if nodes[i].op != SF.OP_JMP]
    idx.sort(key=lambda i: (st[i], nodes[i].dur > 0, i))
    idx += jmp
    out = []
    if rtl in ("r1", "r2", "r3"):
        pend = {}                  # channel -> its unfenced MVGO node
        for i in idx:
            n = nodes[i]
            chans = {nodes[m].chan for m in n.sdeps
                     if live[m] and pend.get(nodes[m].chan) == m}
            if n.op == SF.OP_JMP:
                chans = set(pend)
            if chans:
                out.append(("FENCE", sum(1 << c for c in chans)))
                for c in chans:
                    del pend[c]
            out.append(i)
            if n.kind == "mvgo":
                # (raised directly: the r0 loop below binds a local `need`)
                if n.chan in pend:
                    raise ReorderError(
                        f"MVGO at {n.pc} on mv{n.chan} with the stream of "
                        f"{nodes[pend[n.chan]].pc} unfenced and no "
                        f"stream-edge to it")
                pend[n.chan] = i
        return out
    unfenced = set()
    for i in idx:
        n = nodes[i]
        need = any(live[m] and m in unfenced for m in n.sdeps)
        if nodes[i].op == SF.OP_JMP and unfenced:
            need = True
        if need:
            out.append("FENCE")
            unfenced = set()
        out.append(i)
        if n.kind == "mvgo":
            unfenced.add(i)
    return out


def replay(S, order):
    """One lane, OV1's windows: the time of the EMITTED order (not the
    scheduler's), with start/finish/stream-end per node for the post-check.
    A FENCE waits for the pending streams it drains — every one at r0
    ('FENCE', mask 0), and SR4 at r1 only those on its masked channels;
    the others stay pending."""
    nodes = S["nodes"]
    N = len(nodes)
    tau = [S["groups"][n.grp]["tau"] if n.kind == "mvgo" else 0
           for n in nodes]
    start, fin, send = [None] * N, [None] * N, [None] * N
    t = 0
    pend = []
    for x in order:
        if is_fence(x):
            fm = fence_mask(x)
            sel = [m for m in pend
                   if fm == 0 or (fm >> nodes[m].chan) & 1]
            if sel:
                t = max(t, max(send[m] + tau[m] for m in sel))
            pend = [m for m in pend if m not in sel]
            continue
        n = nodes[x]
        start[x] = t
        t += n.dur
        fin[x] = t
        if n.kind == "mvgo":
            send[x] = t + n.S
            pend.append(x)
    mk = max(t, max((send[i] + tau[i] for i in range(N)
                     if send[i] is not None), default=0))
    post = _r3_post(S, OC.postcheck(nodes, S["live"], start, fin, send, tau, [0] * N), start, fin, send, tau)
    return mk, post, start


def class_keys(S):
    """SR11b: {MVGO node: (layer type, matvec class)} by OV1's own labeller
    (ov_census.segment_matvecs, which labels a decode segment's matvecs by
    the emitter's per-layer order); {} when the segment matches no 9B layer
    order (a synthetic stream) — every stream then takes TAIL1_DEFAULT."""
    nodes, groups = S["nodes"], S["groups"]
    try:
        mvs, _lt = OC.segment_matvecs(nodes, groups)
        keys = {i: (mvs[n.mv]["lt"], mvs[n.mv]["cls"])
                for i, n in enumerate(nodes) if n.kind == "mvgo"}
    except Exception:                       # noqa: BLE001 (no 9B layers)
        return {}
    return keys


def predict(S, order, cmd_extra=None):
    """SR11b: the CORRECTED prediction of an emitted order (ref/seq_cost.py
    FENCE_REC / TAIL1 / CMD_RESID_FRAC, the convention SR5b measured on the
    chip TB).  One lane, OV1's windows for every non-FENCE record (as
    replay()), but a FENCE costs its record — FENCE end = max(t, max over the
    streams it drains (stream end + TAIL1[class])) + FENCE_REC — and the
    inherited CMD residual is added to the makespan.  `cmd_extra` ({node
    index: cycles}, an ATTRIBUTION aid, not a predictor) instead places a
    measured CMD residual in LANE time on the commands it was measured on
    (then nothing is added at the end): a longer command before a FENCE
    shortens that FENCE's wait, which an additive residual cannot show.
    Returns (predicted makespan, info); info["fence_windows"] is each
    emitted FENCE's window in order."""
    nodes = S["nodes"]
    extra = cmd_extra or {}
    keys = class_keys(S)
    tail = {i: SC.fence_tail(keys.get(i)) for i, n in enumerate(nodes)
            if n.kind == "mvgo"}
    t = 0
    pend, send, wins = [], {}, []
    for x in order:
        if is_fence(x):
            fm = fence_mask(x)
            sel = [m for m in pend if fm == 0 or (fm >> nodes[m].chan) & 1]
            t0 = t
            t = max([t] + [send[m] + tail[m] for m in sel]) + SC.FENCE_REC
            pend = [m for m in pend if m not in sel]
            wins.append(t - t0)
            continue
        n = nodes[x]
        t += n.dur + extra.get(x, 0)
        if n.kind == "mvgo":
            send[x] = t + n.S
            pend.append(x)
    lane = max([t] + [send[m] + tail[m] for m in pend])
    cmd = sum(n.dur for i, n in enumerate(nodes)
              if S["live"][i] and n.op == SF.OP_CMD)
    resid = (0 if cmd_extra is not None
             else int(round(SC.CMD_RESID_FRAC * cmd)))
    return lane + resid, {"fence_windows": wins, "lane": lane,
                          "cmd_work": cmd, "cmd_resid": resid,
                          "labelled": bool(keys)}


def arg_owner(nodes):
    """cmd node index -> [arg node indices] in program order, exactly the
    `pend` rule of ov_census.build_nodes (ARG writes ride the next CMD)."""
    own, pend = {}, []
    for i, n in enumerate(nodes):
        if n.kind == "arg":
            pend.append(i)
        elif n.op == SF.OP_CMD:
            own[i] = pend
            pend = []
    need(not pend, "ARG CSRWRs after the last CMD of a segment")
    return own


def banked(r, n):
    """SR11b: the record `r` of census node `n` carrying the bank the model
    assigned (SEQ_ISA v2.3 B17.2): MOVX target = the XWIN start word (1536
    for bank 1; 0 for bank 0 or a span, -1); MVGO SHAPE bit 29 = XBANK, bit
    30 = RBANK (a span, -1, starts at 0); MOVY target[15:4] = the RES start
    row (2048 for bank 1).  Every other field is the input record's."""
    o = r.opcode
    if o == SF.OP_MOVX:
        need(n.bank in (0, 1, -1), f"MOVX at {n.pc}: no bank ({n.bank!r})")
        return SF.Rec(o, flags=r.flags,
                      target=SF.XBANK_WORD if n.bank == 1 else 0,
                      imm32=r.imm32, addr_lo=r.addr_lo,
                      len_or_addr_hi=r.len_or_addr_hi)
    if o == SF.OP_MVGO:
        need(isinstance(n.bank, tuple), f"MVGO at {n.pc}: no bank")
        xb, rb = n.bank
        return SF.Rec(o, flags=r.flags, target=r.target,
                      imm32=(r.imm32 | (SF.SHAPE_XBANK if xb == 1 else 0)
                             | (SF.SHAPE_RBANK if rb == 1 else 0)),
                      addr_lo=r.addr_lo, len_or_addr_hi=r.len_or_addr_hi)
    if o == SF.OP_MOVY:
        need(n.bank in (0, 1, -1), f"MOVY at {n.pc}: no bank ({n.bank!r})")
        row0 = SF.RBANK_ROW if n.bank == 1 else 0
        return SF.Rec(o, flags=r.flags,
                      target=(r.target & 0xF) | (row0 << 4),
                      imm32=r.imm32, addr_lo=r.addr_lo,
                      len_or_addr_hi=r.len_or_addr_hi)
    return r


def emit_segment(recs, S, order, rtl="r0"):
    """-> [(old static index or None, Rec)] for the segment.  SR11b: at r2
    every MOVX / MVGO / MOVY carries the bank the census assigned
    (`banked`)."""
    nodes = S["nodes"]
    own = arg_owner(nodes)
    # an XRF-indirect ARG write resolves when it issues; the model reads its
    # XRF at the CMD (build_nodes merges it), so no XRF writer may sit
    # between such an ARG write and its CMD in program order
    for ci, al in own.items():
        for a in al:
            if nodes[a].xr:
                x = nodes[a].xr
                mid = [j for j in range(a + 1, ci) if nodes[j].xw & x]
                need(not mid, (f"XRF-indirect ARG at {nodes[a].pc}: XRF "
                                 f"{sorted(x)} written before its CMD "
                                 f"{nodes[ci].pc} by {[nodes[j].pc for j in mid]}"))
    items = []
    for x in order:
        if is_fence(x):
            # r0: target 0 (drain all, byte-identical to the pre-SR4 pass);
            # r1: target[3:0] = the channel mask (SEQ_ISA v2.3 B17.1)
            items.append((None, SF.Rec(SF.OP_FENCE, target=fence_mask(x))))
            continue
        n = nodes[x]
        for a in own.get(x, ()):
            items.append((nodes[a].pc, recs[nodes[a].pc]))
        items.append((n.pc, _r3_rec(S, x, banked(recs[n.pc], n)) if rtl in ("r2", "r3")
                      else recs[n.pc]))
    return items


def check_args(recs, lo, hi, items):
    """Every CMD sees, in the new order, the ARG0-2 values it saw in
    program order (seeded with the values in force at the segment start)."""
    def walk(seq, a):
        seen = {}
        a = dict(a)
        for (oi, r) in seq:
            if r.opcode == SF.OP_CSRWR and r.target in ARG_CSRS:
                # (imm32, flags): an XRF-indirect ARG write resolves at issue;
                # its XRF read rides the CMD node (build_nodes), so the XRF
                # edges order it and the RECORD is what must match here
                a[r.target] = (r.imm32, r.flags)
            elif r.opcode == SF.OP_CMD:
                seen[oi] = tuple(a[t] for t in ARG_CSRS)
        return seen
    a0 = {t: None for t in ARG_CSRS}
    old = walk([(i, recs[i]) for i in range(lo, hi + 1)], a0)
    new = walk(items, a0)
    need(old.keys() == new.keys(), "the CMD set changed under the reorder")
    bad = [i for i in old if old[i] != new[i]]
    need(not bad, f"{len(bad)} CMDs see different ARG values, first {bad[:3]}")
    return len(old)


# ======================================================================
# the live-state checkpoints
# ======================================================================
def remap_checkpoints(cps, seg_info, old2new, nnew):
    """cps: [[old index, addr, n]] sorted.  A checkpoint samples scratch
    [addr, addr+n) BEFORE its record issues.  In the new order it may sit
    at any position p with every writer of the region that preceded it in
    program order (within its segment) before p and every later writer at
    or after p — then every word has the same last writer, and so the same
    value.  Positions must also stay strictly increasing (the gate compares
    the sampled regions in firing order).  Greedy-earliest per checkpoint;
    refuses if no position exists.  seg_info: [(lo, hi, new_lo, new_end,
    writers)] with writers = [(old index, [(a, b)...])] in program order,
    new_end the last position a checkpoint of the segment may take."""
    out = []
    last = -1
    moved = 0
    for (oi, a, n) in cps:
        seg = next((s for s in seg_info if s[0] <= oi <= s[1]), None)
        if seg is None:                      # prologue / epilogue: unmoved
            p = old2new[oi]
            lo_p, hi_p = p, p
        else:
            lo, hi, new_lo, new_end, writers = seg
            e, l_ = new_lo, new_end
            for (wi, W) in writers:
                if not any(x < a + n and a < y for (x, y) in W):
                    continue
                pw = old2new[wi]
                if wi < oi:
                    e = max(e, pw + 1)
                else:
                    l_ = min(l_, pw)
            lo_p, hi_p = e, l_
        p = max(lo_p, last + 1)
        if p > hi_p:
            raise ReorderError(
                f"checkpoint at old record {oi} [{a:#x}+{n}] has no legal "
                f"position (window {lo_p}..{hi_p}, previous {last})")
        if oi in old2new and p != old2new[oi]:
            moved += 1
        out.append([p, a, n])
        last = p
    need(not out or out[-1][0] < nnew, "a checkpoint past the stream end")
    return out, moved


# ======================================================================
# the whole stream
# ======================================================================
def reorder(recs, rows_of_seg, form, cps=(), rtl="r0"):
    """rows_of_seg(k, lo, hi) -> rows dict for segment k.  Returns (new
    records, new checkpoints, report).  `rtl` (SR4): "r0" (default; the
    pre-SR4 pass, byte for byte) or "r1" (masked FENCEs, output valid only
    at caps {"R1"}) or "r2" (SR11b: r1 + the XWIN/RES banks, output valid
    only at caps {"R1","R2"})."""
    need(rtl in RTLS, f"--rtl {rtl!r}: this pass emits {RTLS}")
    pro, segs, halt = segments(recs)
    # the input's FENCE groups are OV1's (stream_durations assumes each
    # FENCE drains every pending stream): the pass reorders r0 streams only
    masked_in = [i for i, r in enumerate(recs)
                 if r.opcode == SF.OP_FENCE and r.target & 0xF]
    need(not masked_in, f"the input already carries {len(masked_in)} masked "
                        f"FENCE(s), first at {masked_in[:1]}: the pass "
                        f"reorders r0 streams only")
    # SR11b: the census assigns every bank from program order, so the input
    # carries none (a bank field would be silently re-assigned)
    banked_in = [i for i, r in enumerate(recs)
                 if (r.opcode == SF.OP_MOVX and r.target)
                 or (r.opcode == SF.OP_MOVY and r.target >> 4)
                 or (r.opcode == SF.OP_MVGO
                     and r.imm32 & (SF.SHAPE_XBANK | SF.SHAPE_RBANK))]
    need(not banked_in, f"the input already carries {len(banked_in)} bank "
                        f"field(s) (MOVX target / SHAPE 29-30 / MOVY "
                        f"target[15:4]), first at {banked_in[:1]}: the pass "
                        f"reorders r0 streams only")
    assert_no_pending_hazard(_r3_input(recs), "INPUT")
    items = [(i, recs[i]) for i in range(pro)]
    rep = {"form": form, "rtl": rtl, "segments": []}
    seg_info = []
    body_new_lo = None
    for k, (lo, hi, is_body) in enumerate(segs):
        S = schedule_segment(recs, lo, hi, rows_of_seg(k, lo, hi), form, rtl)
        order = order_and_fences(S, rtl)
        rmk, rpost, _ = replay(S, order)
        seg_items = emit_segment(recs, S, order, rtl)
        nargs = check_args(recs, lo, hi, seg_items)
        new_lo = len(items)
        if is_body:
            body_new_lo = new_lo
            j = seg_items[-1][1]
            need(j.opcode == SF.OP_JMP, "the loop body does not end at its JMP")
            seg_items[-1] = (seg_items[-1][0],
                             SF.Rec(SF.OP_JMP, flags=j.flags, target=j.target,
                                    imm32=new_lo, addr_lo=j.addr_lo,
                                    len_or_addr_hi=j.len_or_addr_hi))
        items += seg_items
        nodes = S["nodes"]
        old_movx = sum(1 for n in nodes if n.kind == "movx")
        nf_in = sum(1 for n in nodes if n.kind == "fence")
        nf_out = sum(1 for x in order if is_fence(x))
        masks = collections.Counter(fence_mask(x) for x in order
                                    if is_fence(x))
        # a fence is DEFERRED when non-group work now sits between a group's
        # last MVGO and the FENCE that drains it
        deferred = 0
        gap = 0
        seen_mvgo = False
        for x in order:
            if is_fence(x):
                if seen_mvgo and gap:
                    deferred += 1
                seen_mvgo, gap = False, 0
            elif nodes[x].kind == "mvgo":
                seen_mvgo, gap = True, 0
            elif seen_mvgo:
                gap += 1
        writers = [(n.pc, list(n.W)) for n in nodes
                   if n.W and not (n.kind == "movx")]
        rep["segments"].append({
            "k": k, "lo": lo, "hi": hi, "body": is_body,
            "records_in": hi - lo + 1, "records_out": len(seg_items),
            "movx_in": old_movx, "movx_elided": S["nred"],
            "fences_in": nf_in, "fences_out": nf_out,
            "fences_deferred": deferred, "sched_fences": S["sched_fences"],
            "rule": S["rule"], "sched_mk": S["mk"], "replay_mk": rmk,
            "orig_win": S["orig_win"], "post_sched": S["post"],
            "post_replay": rpost, "trials": S["trials"], "cmds_args": nargs,
            "leak": S["leak"],
            "jmp_win": sum(n.dur for n in nodes if n.op == SF.OP_JMP)})
        if rtl != "r0":
            rep["segments"][-1]["fence_masks"] = dict(sorted(masks.items()))
        if rtl in ("r2", "r3"):
            # SR11b: the corrected prediction beside the census's replay,
            # and the banks emitted (bank 1 fields; spans at 0)
            pmk, pinfo = predict(S, order)
            bk = collections.Counter()
            for (_oi, r) in seg_items:
                if r.opcode == SF.OP_MOVX:
                    bk["MOVX word 1536" if r.target else "MOVX word 0"] += 1
                elif r.opcode == SF.OP_MVGO:
                    bk["XBANK"] += bool(r.imm32 & SF.SHAPE_XBANK)
                    bk["RBANK"] += bool(r.imm32 & SF.SHAPE_RBANK)
                    bk["MVGO"] += 1
                elif r.opcode == SF.OP_MOVY:
                    bk["MOVY row 2048" if r.target >> 4 else "MOVY row 0"] += 1
            rep["segments"][-1].update({
                "pred_mk": pmk, "pred_lane": pinfo["lane"],
                "pred_cmd_resid": pinfo["cmd_resid"],
                "pred_labelled": pinfo["labelled"],
                "banks": dict(sorted(bk.items()))})
        seg_info.append(_r3_seg(rep, S, seg_items, new_lo, rtl) or [lo, hi, new_lo, None, writers, is_body])
    items += [(i, recs[i]) for i in range(segs[-1][1] + 1, len(recs))]
    new = [r for (_oi, r) in items]
    old2new = {}
    for p, (oi, _r) in enumerate(items):
        if oi is not None:
            old2new[oi] = p
    # S1P: the permutation, so a caller can make a patch follow its record
    rep["old2new"] = old2new
    # the latest legal checkpoint slot of a segment: before its first record
    # of the next segment, or, for the loop body, before its JMP
    for s in seg_info:
        nxt = [t[2] for t in seg_info if t[2] > s[2]]
        end = min(nxt) if nxt else len(new) - 1
        s[3] = end - 1 if s[5] else end
    rep["body_new_lo"] = body_new_lo
    newcps, moved = remap_checkpoints(
        sorted([list(c) for c in cps]),
        [tuple(s[:5]) for s in seg_info], old2new, len(new))
    rep["checkpoints"] = len(newcps)
    rep["checkpoints_moved"] = moved
    rep["hazard"] = assert_no_pending_hazard(new, "OUTPUT")
    if rtl == "r0":
        SF.validate_stream(new)
    else:
        # SR4: valid at the device capability set the level needs (the
        # caps= argument, SEQ_ISA v2.3 B17.0) — and REFUSED at the empty
        # set (build_041/042), which is what makes an r1 stream fail
        # closed on a pre-round bitstream
        caps = CAPS_OF[rtl]
        SF.validate_stream(new, caps=caps)
        nmask = sum(1 for r in new if r.opcode == SF.OP_FENCE and r.target)
        try:
            SF.validate_stream(new)
            refused = False
        except SF.SeqValidationError:
            refused = True
        need(refused or not nmask,
             f"an {rtl} stream with {nmask} masked FENCEs validated at the "
             f"EMPTY capability set")
        rep["caps"] = sorted(caps)
        rep["refused_at_empty"] = refused
        rep["fence_masks"] = dict(sorted(collections.Counter(
            r.target & 0xF for r in new if r.opcode == SF.OP_FENCE).items()))
        if rtl in ("r2", "r3"):
            # SR11b: an r2 stream must ALSO be refused at {"R1"} (an R1
            # bitstream ignores MOVX target and drops SHAPE 29/30: R2 is
            # NOT fail-closed, B17.2) whenever it carries a bank-1 field
            nbank = sum(1 for r in new
                        if (r.opcode == SF.OP_MOVX and r.target)
                        or (r.opcode == SF.OP_MOVY and r.target >> 4)
                        or (r.opcode == SF.OP_MVGO and r.imm32
                            & (SF.SHAPE_XBANK | SF.SHAPE_RBANK)))
            try:
                SF.validate_stream(new, caps=CAPS_OF["r1"])
                refused1 = False
            except SF.SeqValidationError:
                refused1 = True
            need(refused1 or not nbank,
                 f"an r2 stream with {nbank} bank fields validated at "
                 f"{{R1}}")
            rep["refused_at_r1"] = refused1
            rep["bank_fields"] = _r3_admit(new, rep, rtl, nbank)
    return new, newcps, rep


# ======================================================================
# measured windows: BN1's CSV of model_9b_s1, mapped by segment skeleton
# ======================================================================
class Windows(object):
    def __init__(self):
        trecs = SF.unpack_stream(open(TEMPLATE + ".seq", "rb").read())
        man = json.load(open(TEMPLATE + ".seq.json"))
        got = hashlib.sha256(SF.pack_stream(trecs)).hexdigest()
        need(got == man["stream_sha256"], "template stream sha mismatch")
        print(f"=== window template {TEMPLATE}.seq sha256 {got[:16]} MATCH")
        self.rows = OC.load_csv(toks=(1, 2, 3, 4))
        _pro, tsegs, _h = segments(trecs)
        self.tsegs = []
        for k, (lo, hi, body) in enumerate(tsegs):
            self.tsegs.append((skeleton(trecs, lo, hi), lo, hi, k + 1))
        print("    template segments (tok: lo..hi): " + ", ".join(
            f"tok{t}: {lo}..{hi}" for (_s, lo, hi, t) in self.tsegs))

    def rows_for(self, recs):
        def f(k, lo, hi):
            sk = skeleton(recs, lo, hi)
            m = [t for t in self.tsegs if t[0] == sk]
            if not m:
                raise ReorderError(
                    f"segment {k} ({lo}..{hi}) matches no template segment's "
                    "skeleton — no measured windows for it")
            pref = [t for t in m if t[3] == k + 1]
            _s, tlo, thi, tok = (pref or m)[0]
            print(f"    segment {k} ({lo}..{hi}) <- template tok{tok} "
                  f"({tlo}..{thi}) windows")
            R = self.rows[tok]
            return {lo + d: R[tlo + d] for d in range(hi - lo + 1)}
        return f


def write_out(out, src, new, newcps, rep):
    meta = json.load(open(src + ".seq.json"))
    stream = SF.pack_stream(new)
    with open(out + ".seq", "wb") as f:
        f.write(stream)
    shutil.copyfile(src + ".seqdata.bin", out + ".seqdata.bin")
    meta["nrec"] = len(new)
    meta["stream_bytes"] = len(stream)
    meta["stream_sha256"] = hashlib.sha256(stream).hexdigest()
    meta["checkpoints"] = newcps
    meta["opcode_histogram"] = {
        SF.OP_NAME[o]: sum(1 for r in new if r.opcode == o)
        for o in sorted(SF.ALL_OPS) if any(r.opcode == o for r in new)}
    meta["sv1_reorder"] = {
        "source": src, "source_sha256": json.load(
            open(src + ".seq.json"))["stream_sha256"],
        "form": rep["form"], "tool": "ref/scripts/reorder_e4.py",
        "cost": rep.get("cost", "csv"),
        "segments": [{k: v for k, v in s.items() if k != "trials"}
                     for s in rep["segments"]]}
    if rep.get("rtl", "r0") != "r0":
        # SR4: INFORMATIONAL (admission is keyed by the DEVICE's SEQ_CAPS,
        # never by this list — SEQ_ISA v2.3 B17.0 ADMISSION); nothing new
        # is written at r0
        meta["seq_isa"] = "2.3"
        meta["caps"] = list(rep["caps"])
        meta["sv1_reorder"]["rtl"] = rep["rtl"]
        meta["sv1_reorder"]["fence_masks"] = {
            f"{m:#06b}": c for m, c in rep["fence_masks"].items()}
        if rep["rtl"] in ("r2", "r3"):
            # SR11b: informational, as the caps are
            meta["sv1_reorder"]["bank_fields"] = rep["bank_fields"]
            meta["sv1_reorder"]["refused_at_r1"] = _r3_meta(meta, rep)
    with open(out + ".seq.json", "w") as f:
        json.dump(meta, f, indent=1)
    return meta["stream_sha256"]


def print_report(rep):
    ms = OC.ms
    for s in rep["segments"]:
        print(f"--- segment {s['k']} static {s['lo']}..{s['hi']}"
              f"{' (LOOP BODY)' if s['body'] else ''}: records "
              f"{s['records_in']} -> {s['records_out']}")
        print(f"    MOVX {s['movx_in']} -> {s['movx_in'] - s['movx_elided']}"
              f"  ELIDED {s['movx_elided']};  FENCE {s['fences_in']} -> "
              f"{s['fences_out']} (scheduler fenced {s['sched_fences']}); "
              f"fences DEFERRED past independent work: "
              f"{s['fences_deferred']}")
        for (h, mk, post) in s["trials"]:
            print(f"      (heuristic {h}: {mk} cyc = {ms(mk):.3f} ms; "
                  f"POSTCHECK {post[0]} edges + {post[1]} checks)")
        print(f"    schedule rule {s['rule']}: {s['sched_mk']} cyc = "
              f"{ms(s['sched_mk']):.3f} ms  (program order, measured: "
              f"{s['orig_win']} cyc = {ms(s['orig_win']):.3f} ms)")
        print(f"    replay of the EMITTED order: {s['replay_mk']} cyc = "
              f"{ms(s['replay_mk']):.3f} ms  "
              f"(replay - scheduler = {s['replay_mk'] - s['sched_mk']:+d} cyc; the JMP window is {s['jmp_win']}: the scheduler may place the JMP early, the stream cannot)")
        print(f"    POSTCHECK on the emitted order: {s['post_replay'][0]} "
              f"edges + {s['post_replay'][1]} channel/lane checks, 0 "
              f"violations;  ARG values checked on {s['cmds_args']} CMDs")
        if "fence_masks" in s:
            print("    FENCE masks (target[3:0] -> count): " + ", ".join(
                f"{m:04b} x{c}" for m, c in s["fence_masks"].items()))
    h = rep["hazard"]
    print(f"=== OUTPUT hazard assert: PASS over the whole stream "
          f"(MOVX {h['MOVX']}, MVGO {h['MVGO']}, MOVY {h['MOVY']}, "
          f"FENCE {h['FENCE']}; none on a pending channel, none pending at "
          f"JMP/HALT)")
    print(f"=== checkpoints: {rep['checkpoints']} carried, "
          f"{rep['checkpoints_moved']} not at their own record's new "
          f"position")


# ======================================================================
# selftest — a synthetic stream: a fence deferred, a MOVX elided, a
# hazard refused
# ======================================================================
def _synthetic():
    import hwmap as HW
    c, nrows, S = 0, 4, 1000
    shape = HW.shape_word(nrows, 0, 1)

    def movx(src):
        return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), addr_lo=src,
                      len_or_addr_hi=128)

    def mvgo():
        return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                      target=SF.MVGO_NOWAIT, imm32=shape,
                      addr_lo=HW.W_BASE & 0xFFFFFFFF,
                      len_or_addr_hi=(nrows << 8))

    def movy(dst):
        return SF.Rec(SF.OP_MOVY, flags=SF.MOVY_MODE_BIT, target=c,
                      addr_lo=dst, len_or_addr_hi=nrows)

    def arg(t, v):
        return SF.Rec(SF.OP_CSRWR, target=t, imm32=v)

    recs = [
        SF.Rec(SF.OP_CSRWR, target=SF.CSR_SEQ_TCNT, imm32=2),   # 0 prologue
        SF.Rec(SF.OP_EMB, addr_lo=0x100, len_or_addr_hi=128),   # 1 x source
        movx(0x100),                                            # 2
        mvgo(),                                                 # 3
        SF.Rec(SF.OP_FENCE),                                    # 4
        movy(0x400),                                            # 5
        arg(SF.CSR_L_ARG0, 6 << 2),                             # 6 VN x64
        arg(SF.CSR_L_ARG1, GLS.enc_a1(0x800, 0x900)),           # 7
        arg(SF.CSR_L_ARG2, 0),                                  # 8
        SF.Rec(SF.OP_CMD, imm32=1),                             # 9 independent
        movx(0x100),                                            # 10 REDUNDANT
        mvgo(),                                                 # 11
        SF.Rec(SF.OP_FENCE),                                    # 12
        movy(0x500),                                            # 13
        SF.Rec(SF.OP_JMP, flags=SF.JMP_TCNT, imm32=1),          # 14
        SF.Rec(SF.OP_HALT),                                     # 15
    ]
    dur = {SF.OP_EMB: 200, SF.OP_MOVX: 100, SF.OP_MVGO: 10,
           SF.OP_MOVY: 50, SF.OP_CSRWR: 5, SF.OP_CMD: 500, SF.OP_JMP: 3}
    rows, t = {}, 0
    for pc in range(1, 15):
        o = recs[pc].opcode
        cls = [0] * 16
        if o == SF.OP_MVGO:
            cls[OC.BSY0 + c] = S
        d = (S + 40) if o == SF.OP_FENCE else dur[o]
        rows[pc] = (o, t, d, cls)
        t += d
    cps = [[5, 0x400, 4], [10, 0x400, 4], [13, 0x500, 4]]
    return recs, rows, cps


def _synthetic_static():
    """_synthetic() with shapes ref/seq_cost.py prices (S1P): EMB x4096, VN
    rmsnorm0 x256, 8448-beat streams (S 7187 >> the VN's 598-cycle node, so
    deferring the fence past it pays)."""
    recs, _rows, cps = _synthetic()
    recs = list(recs)
    recs[1] = SF.Rec(SF.OP_EMB, addr_lo=0x100, len_or_addr_hi=4096)
    for i in (3, 11):
        r = recs[i]
        recs[i] = SF.Rec(SF.OP_MVGO, flags=r.flags, target=r.target,
                         imm32=r.imm32, addr_lo=r.addr_lo,
                         len_or_addr_hi=(8448 << 8))
    recs[6] = SF.Rec(SF.OP_CSRWR, target=SF.CSR_L_ARG0, imm32=8 << 2)
    return recs, cps


def selftest_static():
    """S1P: `--cost static` is the default, prices a stream no CSV covers
    without reading the CSV, gives the same S1 transformation as the
    hand-timed synthetic, and refuses what its table cannot price."""
    # (seq_cost imported at module level)
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [static] [{'PASS' if cond else 'FAIL'}] {name}"
              + (f"  {detail}" if detail else ""))
    try:
        a = build_parser().parse_args(["--in", "x"])
        check("--cost defaults to static", a.cost == "static", a.cost)
        # the CSV path must not be touched: make it explode
        real = OC.load_csv

        def boom(*_a, **_k):
            raise RuntimeError("the CSV was read")
        OC.load_csv = boom
        try:
            recs, cps = _synthetic_static()
            f = rows_provider("static", recs)
            for form in ("A", "B"):
                new, newcps, rep = reorder(recs, f, form, cps)
                s = rep["segments"][0]
                names = [SF.OP_NAME[r.opcode] for r in new]
                i_mvgo, i_fence = names.index("MVGO"), names.index("FENCE")
                deferred = names[i_mvgo + 1:i_fence] == [
                    "CSRWR", "CSRWR", "CSRWR", "CMD"]
                check(f"form {form}: fence deferred past the VN, MOVX elided, "
                      f"no CSV read", deferred and s["movx_elided"] == 1
                      and names.count("MOVX") == 1, " ".join(names))
        finally:
            OC.load_csv = real
        # fail-closed: the hand-timed synthetic carries shapes the table
        # does not price (EMB x128, VN x64)
        recs0, _rows, cps0 = _synthetic()
        try:
            reorder(recs0, rows_provider("static", recs0), "B", cps0)
            check("an unpriceable stream is refused", False, "reordered it")
        except SC.StaticCostError as e:
            check("an unpriceable stream is refused", True, str(e))
    except Exception as e:                  # noqa: BLE001
        check("static cost path", False, f"{type(e).__name__}: {e}")
    return ok
def selftest():
    ok = True
    for form in ("A", "B"):
        recs, rows, cps = _synthetic()
        new, newcps, rep = reorder(recs, lambda k, lo, hi: rows, form, cps)
        s = rep["segments"][0]
        names = [SF.OP_NAME[r.opcode] for r in new]
        print(f"[{form}] out: {' '.join(names)}")
        print(f"[{form}] checkpoints {cps} -> {newcps}")
        i_mvgo = names.index("MVGO")
        i_fence = names.index("FENCE")
        deferred = (i_fence - i_mvgo - 1) == 4 and \
            names[i_mvgo + 1:i_fence] == ["CSRWR", "CSRWR", "CSRWR", "CMD"]
        elided = (names.count("MOVX") == 1 and s["movx_elided"] == 1)
        jmp_ok = (new[-2].opcode == SF.OP_JMP and new[-2].imm32 == 1)
        # the emitted order may cost the scheduler's makespan plus at most the
        # JMP window: the scheduler may place the JMP early, the stream cannot
        timed = (0 <= s["replay_mk"] - s["sched_mk"] <= s["jmp_win"]
                 and s["replay_mk"] < s["orig_win"])
        cp_ok = [p for p, _a, _n in newcps] == sorted(
            p for p, _a, _n in newcps) and \
            newcps[1][0] > names.index("MOVY") and \
            newcps[2][0] <= len(new) - 2
        # the hazard: every legal output passes, and each of the three
        # ways to break it is refused
        refused = 0
        for bad in (
                # a MOVX hoisted above the FENCE of the stream on its channel
                [new[j] for j in (0, 1, 2, 3)] + [recs[2]] + new[4:],
                # a second MVGO on the running channel
                [new[j] for j in (0, 1, 2, 3)] + [recs[3]] + new[4:],
                # the loop's FENCE dropped: MOVY on a pending channel
                [r for r in new if r.opcode != SF.OP_FENCE]):
            try:
                assert_no_pending_hazard(bad)
            except HazardError as e:
                refused += 1
                print(f"[{form}] refused: {e}")
        good = deferred and elided and jmp_ok and timed and cp_ok and \
            refused == 3
        print(f"[{form}] fence deferred {deferred}; MOVX elided {elided}; "
              f"JMP -> body start {jmp_ok}; replay {s['replay_mk']} - "
              f"schedule {s['sched_mk']} <= JMP window {s['jmp_win']}, < program order {s['orig_win']}: "
              f"{timed}; checkpoints {cp_ok}; hazards refused {refused}/3 "
              f"-> {'PASS' if good else 'FAIL'}")
        ok &= good
    ok &= selftest_static()
    ok &= selftest_r2() & selftest_r3()
    print("REORDER_E4 SELFTEST: " + ("PASS" if ok else "FAIL"))
    return ok


def selftest_r2():
    """SR11b: at r2 the synthetic's first MOVX loads XWIN bank 1 (word
    1536), its MVGOs carry XBANK (both read the surviving copy — the second
    MOVX is elided) and alternate RBANK, the MOVYs drain 2048 / 0; the
    output is valid at {R1,R2} only, passes the range-aware hazard assert,
    and replays no slower than r1."""
    ok = True
    for form in ("A", "B"):
        recs, rows, cps = _synthetic()
        n1, _c1, r1 = reorder(recs, lambda k, lo, hi: rows, form, cps,
                              rtl="r1")
        recs, rows, cps = _synthetic()
        n2, _c2, r2 = reorder(recs, lambda k, lo, hi: rows, form, cps,
                              rtl="r2")
        mx = [r.target for r in n2 if r.opcode == SF.OP_MOVX]
        mg = [((r.imm32 >> 29) & 1, (r.imm32 >> 30) & 1) for r in n2
              if r.opcode == SF.OP_MVGO]
        my = [r.target >> 4 for r in n2 if r.opcode == SF.OP_MOVY]
        s1, s2 = r1["segments"][0], r2["segments"][0]
        good = (mx == [SF.XBANK_WORD] and mg == [(1, 1), (1, 0)]
                and my == [SF.RBANK_ROW, 0] and r2["refused_at_r1"]
                and r2["refused_at_empty"] and r2["caps"] == ["R1", "R2"]
                and s2["replay_mk"] <= s1["replay_mk"])
        print(f"[r2 {form}] MOVX words {mx}; MVGO (XBANK, RBANK) {mg}; MOVY "
              f"rows {my}; refused at {{R1}} {r2['refused_at_r1']}, at {{}} "
              f"{r2['refused_at_empty']}; replay r2 {s2['replay_mk']} <= r1 "
              f"{s1['replay_mk']}; predicted {s2['pred_mk']} -> "
              f"{'PASS' if good else 'FAIL'}")
        ok &= good
    return ok


def rows_provider(cost, recs, pos0=0):
    """S1P: the rows_of_seg(k, lo, hi) the pass schedules with.  "static"
    never opens the CSV; "csv" is SV1's skeleton-matched template windows."""
    if cost == "static":
        print(f"=== cost source: STATIC ref/seq_cost.py (segment k priced at "
              f"position {pos0} + k; no CSV read)")
        return SC.rows_for(recs, pos0)
    need(cost == "csv", f"unknown cost source {cost!r}")
    print("=== cost source: CSV (BN1 timeline of model_9b_s1, skeleton-"
          "matched)")
    return Windows().rows_for(recs)


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--in", dest="src", help=".e4 prefix to reorder")
    ap.add_argument("--out", help=".e4 prefix to write (refuses to overwrite)")
    ap.add_argument("--form", choices=("A", "B"), default="B")
    ap.add_argument("--cost", choices=COSTS, default="static",
                    help="S1P: per-record windows from ref/seq_cost.py "
                         "(static, the default) or BN1's CSV (csv, SV1's "
                         "path — reproduces the SV1 pins)")
    ap.add_argument("--pos0", type=int, default=0,
                    help="static cost: the position of segment 0 (ATTN "
                         "grows with it); segment k is priced at pos0 + k")
    ap.add_argument("--stats", action="store_true",
                    help="print the per-segment report")
    ap.add_argument("--rtl", choices=RTLS, default="r0",
                    help="SR4: the RTL level emitted for — r0 (default, the "
                         "shipped RTL: every FENCE drains all channels) or "
                         "r1 (SEQ_ISA v2.3 B17.1 FENCE channel mask; the "
                         "output validates only at caps {R1}) or r2 "
                         "(SR11b: r1 + B17.2 XWIN/RES banks; valid only "
                         "at caps {R1,R2})")
    return ap


def main():
    a = build_parser().parse_args()
    if a.selftest:
        if not selftest():
            raise SystemExit(1)
    if a.src:
        src = a.src
        stream = open(src + ".seq", "rb").read()
        meta = json.load(open(src + ".seq.json"))
        sha = hashlib.sha256(stream).hexdigest()
        need(sha == meta["stream_sha256"], "input stream sha mismatch")
        print(f"=== input {src}.seq sha256 {sha[:16]} MATCH, "
              f"{meta['nrec']} records, form {a.form}, cost {a.cost}"
              + ("" if a.rtl == "r0" else f", rtl {a.rtl}"))
        recs = SF.unpack_stream(stream)
        new, newcps, rep = reorder(recs, rows_provider(a.cost, recs, a.pos0),
                                   a.form, meta.get("checkpoints", []),
                                   rtl=a.rtl)
        rep["cost"] = a.cost
        if a.stats:
            print_report(rep)
        if a.rtl != "r0":
            segs = rep["segments"]
            body = [s for s in segs if s["body"]]
            print(f"=== {a.rtl}: FENCE masks over the stream (target[3:0] -> "
                  f"count): " + ", ".join(f"{m:04b} x{c}" for m, c in
                                         rep["fence_masks"].items()))
            print(f"=== {a.rtl}: validated at caps {rep['caps']}; refused at "
                  f"the empty set: {rep['refused_at_empty']}")
            print(f"=== {a.rtl}: replay makespan of the emitted order per "
                  f"segment: " + ", ".join(
                      f"seg{s['k']} {s['replay_mk']}" for s in segs)
                  + (f"; LOOP BODY {body[0]['replay_mk']} cyc (scheduler "
                     f"{body[0]['sched_mk']})" if body else ""))
            if a.rtl == "r2" or _r3_print(rep, a.rtl):
                print(f"=== r2: refused at caps ['R1']: "
                      f"{rep['refused_at_r1']}; bank fields in the stream "
                      f"(MOVX target / SHAPE 29-30 / MOVY target[15:4] "
                      f"non-zero): {rep['bank_fields']}")
                for s in segs:
                    print(f"=== r2: seg{s['k']} banks " + ", ".join(
                        f"{k} {v}" for k, v in s["banks"].items()))
                print("=== r2: CORRECTED prediction (seq_cost FENCE_REC / "
                      "TAIL1 / CMD_RESID_FRAC) per segment: " + ", ".join(
                          f"seg{s['k']} {s['pred_mk']}" for s in segs)
                      + (f"; LOOP BODY {body[0]['pred_mk']} cyc (lane "
                         f"{body[0]['pred_lane']} + CMD residual "
                         f"{body[0]['pred_cmd_resid']}; classes labelled "
                         f"{body[0]['pred_labelled']})" if body else ""))
        print(f"=== output {len(new)} records (input {len(recs)}); "
              f"checkpoints {len(newcps)}")
        if a.out:
            for sfx in (".seq", ".seqdata.bin", ".seq.json", ".chip"):
                if os.path.exists(a.out + sfx):
                    raise SystemExit(f"REFUSING: {a.out + sfx} exists")
            osha = write_out(a.out, src, new, newcps, rep)
            print(f"=== wrote {a.out}.seq sha256 {osha}")
            print(f"=== wrote {a.out}.seqdata.bin (copy), {a.out}.seq.json")


# ======================================================================
# SEQ_ISA B17.3 (R3): the MOVX BROADCAST -- Task R3-5 of the R3 campaign
# (docs/superpowers/plans/2026-09-29-r3-broadcast.md).  Everything R3 adds to
# this pass lives HERE, after every line other documents cite, so no citation
# moves (the SR14 §7 zero-drift rule, R3-2's / R3-3's layout): the functions
# above reach it through one-line rewrites (assert_no_pending_hazard's
# channel, schedule_segment's edges and its S, order_and_fences' level,
# replay's post-check, emit_segment's record, reorder's input / report /
# admission, write_out's manifest, main's print, selftest's call).  Names
# resolve at call time, so defining them after their callers is ordinary
# Python; RTLS / CAPS_OF / DEPTH gain "r3" below, before any call.
#
# `--rtl r3` = r2 (the census's depth-2 edges, masked FENCEs, the banks it
# assigns) plus a REAL broadcast node.  After ov_census.build_edges, every
# run of MOVX records (a matvec's MOVX, XOPs allowed between, as
# ov_census.segment_matvecs cuts them) is split by (source range, length)
# over its LIVE (not elided) MOVX; a key group with exactly one MOVX on each
# of channels 0..3 becomes ONE node, the CARRIER = its first MOVX (the
# census's carrier, ov_census.py R3 variant): its window is the carrier's,
# its done- and stream-edges the UNION of the four siblings' (it waits on
# the LATEST of the four channels' readers, OV1_DEPENDENCY_CENSUS.md
# :771-773), every edge onto a sibling is redirected to it, and the siblings
# leave the live set (marked `redundant`, which is how ov_census.schedule
# and this pass's `live` drop a node).  Any other key group (1-3 MOVX, or
# channels repeated) stays unicast and is COUNTED (unicast-left).
#
# THE BANK (spec §1.3 "Emitter / pass", plan default 5; the model has no
# bank-forcing logic, task-R3-3-review.md).  The broadcast writes ONE
# window on all four channels, so the pass re-walks the XWIN state of
# ov_census.build_edges (the census's own rule, ported line for line in
# _r3_xwin and CHECKED against it on every r3 segment: re-walked with no
# merge it must reproduce build_edges' XWIN edges and banks exactly) with
# each broadcast at its carrier: the bank is channel 0's census bank; a
# channel whose own rotation would have chosen the other bank is FORCED onto
# channel 0's (its WAR edges then come from ITS last readers of the forced
# bank — the added edge — and its XWIN writer / rotation state follow the
# forced bank, so its consuming MVGO reads the forced bank's XBANK and its
# later rotation continues from there).  A K > 6144 vector spans both banks
# on every channel (word 0) and forces nothing.  The consumers are then
# ASSERTED per destination (assert_bcast_consumers): every MVGO whose x the
# re-walk says a broadcast wrote carries XBANK = that broadcast's window,
# else HazardError naming both records (the model would read the other
# window silently if it held an intact vector).
#
# The hazard assert above meets chan 0xF by name (_r3_chan): a broadcast
# MOVX is checked against EVERY channel's pending x range (B17.3 NO RTL
# INTERLOCK, per destination); a MOVX/MVGO/MOVY naming any other channel
# >= 4 is refused.  The pass REFUSES an input carrying a broadcast (the
# census keys XWIN state and elision per channel 0..3; ov_census.py:669-674
# would KeyError on channel 15).  The post-check of the schedule and of the
# replayed order is extended to every destination channel of a broadcast
# (ov_census.postcheck's (x) rule, _r3_xcheck).  Admission: valid at
# {R1,R2,R3}, and — whenever a broadcast is present — REFUSED at {R1,R2}
# (an r3 stream also carries B17.2 bank fields, which are NOT fail-closed:
# the refusal must be the validator's), at {R1} and at {} (r2's checks).
# The manifest records seq_isa 2.3, caps [R1,R2,R3] (informational), keeps
# shape_isa (required at r3) and the broadcast / forced / unicast-left
# counts.  r0 / r1 / r2 are untouched: every hook returns its r2 value when
# rtl != "r3".
# ======================================================================
RTLS = RTLS + ("r3",)
CAPS_OF["r3"] = frozenset({"R1", "R2", "R3"})
DEPTH["r3"] = 2
_R3_XKINDS = {"movx": "xwin-waw", "mvgo": "xwin-raw"}


def _r3_chan(r, i, pend, where):
    """assert_no_pending_hazard's channel (called for MOVX / MVGO / MOVY
    only).  A BROADCAST MOVX (flags[7:4] = 0xF) is checked here against
    every pending channel's x range and returns 0xF, which is no key of
    `pend`, so the per-channel code below it applies nothing more; any other
    channel field >= 4 is refused BY NAME (never filed under a channel no
    engine has)."""
    c = r.chan
    name = SF.OP_NAME[r.opcode]
    if r.opcode == SF.OP_MOVX and c == SF.MOVX_BCAST:
        w0 = r.target & SF.MOVX_WORD_MASK
        a = (w0, w0 + SF.movx_words(r.len_or_addr_hi & 0xFFFFFF))
        for ch in sorted(pend):
            p, rg = pend[ch]
            if _overlap(a[0], a[1], rg[0], rg[1]):
                raise HazardError(
                    f"{where}: record {i} broadcast MOVX (chan 0xF) writes "
                    f"XWIN words {a} on every channel while the no-wait MVGO "
                    f"at record {p} on mv{ch} still reads x words {rg[:2]} "
                    f"(no FENCE covering mv{ch} between; B17.3, per "
                    f"destination)")
        return SF.MOVX_BCAST
    if c > 3:
        raise HazardError(
            f"{where}: record {i} {name} names channel field {c:#x}: no "
            f"engine channel has it (only a MOVX broadcasts, chan 0xF, "
            f"B17.3)")
    return c


def _r3_input(recs):
    """reorder()'s INPUT check: the census keys XWIN state and elision per
    channel 0..3, so an input broadcast is refused here, by name."""
    b = [i for i, r in enumerate(recs)
         if r.opcode == SF.OP_MOVX and r.chan == SF.MOVX_BCAST]
    need(not b, f"the input already carries {len(b)} broadcast MOVX (chan "
                f"0xF, B17.3), first at {b[:1]}: the pass reorders r0 "
                f"streams only (the census keys XWIN state and MOVX elision "
                f"per channel 0..3)")
    return recs


def _r3_edge_snapshot(nodes):
    return [(dict(n.preds), set(n.sdeps), n.bank) for n in nodes]


def _r3_xwin(nodes, carriers):
    """Re-walk the XWIN part of ov_census.build_edges (xdepth 2) — the
    MOVX WAR stream-edges ('sdeps' of a MOVX are only these), the MOVX
    'xwin-waw' and MVGO 'xwin-raw' done-edges, the MOVX bank and the MVGO
    XBANK — with each broadcast (carriers: {carrier: [its four members]})
    written at its carrier on every member's channel.  Elided MOVX
    (`redundant`, set by build_edges) are skipped as build_edges skips them.
    -> (forced [(carrier, chan, natural bank, forced bank, {WAR readers
    added})], xsrc {MVGO node: the MOVX node whose x it reads})."""
    member = {m: car for car, mem in carriers.items() for m in mem}
    for n in nodes:
        k = _R3_XKINDS.get(n.kind)
        if k is None:
            continue
        n.preds = {p: v for p, v in n.preds.items() if v != k}
        if n.kind == "movx":
            n.sdeps = set()
    xw = {c: [{"w": -1, "r": []} for _ in range(2)] for c in range(4)}
    xsel = {c: 0 for c in range(4)}
    forced, xsrc = [], {}

    def write(i, n, c, b, dbl):
        banks = [b] if dbl else [0, 1]
        for bb in banks:
            buf = xw[c][bb]
            for m in buf["r"]:          # WAR: the engine reads x all stream
                n.sdeps.add(m)
            if buf["w"] >= 0 and buf["w"] != i:
                n.preds.setdefault(buf["w"], "xwin-waw")
            buf["w"], buf["r"] = i, []
    for i, n in enumerate(nodes):
        if n.kind == "movx":
            if n.redundant:
                continue
            dbl = n.n_in <= 6144
            if i in member:
                if member[i] != i:
                    continue            # a sibling: written at its carrier
                mem = carriers[i]
                b0 = (xsel[0] ^ 1) if dbl else xsel[0]
                for m in mem:
                    c = nodes[m].chan
                    bc = (xsel[c] ^ 1) if dbl else xsel[c]
                    if dbl and bc != b0:
                        forced.append((i, c, bc, b0, set(xw[c][b0]["r"])))
                    b = b0 if dbl else bc
                    xsel[c] = b
                    write(i, n, c, b, dbl)
                n.bank = b0 if dbl else -1
                continue
            c = n.chan
            b = (xsel[c] ^ 1) if dbl else xsel[c]
            xsel[c] = b
            n.bank = b if dbl else -1
            write(i, n, c, b, dbl)
        elif n.kind == "mvgo":
            c = n.chan
            buf = xw[c][xsel[c]]
            if buf["w"] >= 0:
                n.preds.setdefault(buf["w"], "xwin-raw")
                xsrc[i] = buf["w"]
            xspan = buf["w"] >= 0 and nodes[buf["w"]].bank == -1
            if xspan:
                for bb in (0, 1):
                    xw[c][bb]["r"].append(i)
            else:
                buf["r"].append(i)
            n.bank = (-1 if xspan else xsel[c], n.bank[1])
    return forced, xsrc


def _r3_groups(nodes):
    """-> (carriers {first MOVX: [the four, by node order]}, unicast-left
    key groups, unicast-left MOVX).  A run = consecutive MOVX nodes (XOPs
    between allowed: ov_census.segment_matvecs' cut); within it the live
    MOVX are keyed by (source range, length)."""
    runs, cur = [], None
    for i, n in enumerate(nodes):
        if n.kind == "movx":
            if cur is None:
                cur = []
                runs.append(cur)
            cur.append(i)
        elif not (n.kind == "chain" and n.op == SF.EXT_XOP):
            cur = None
    carriers, lg, lm = {}, 0, 0
    for run in runs:
        keyed = collections.OrderedDict()
        for i in run:
            if not nodes[i].redundant:
                keyed.setdefault((tuple(nodes[i].R), nodes[i].n_in),
                                 []).append(i)
        for mem in keyed.values():
            if sorted(nodes[m].chan for m in mem) == [0, 1, 2, 3]:
                carriers[mem[0]] = mem
            else:
                lg += 1
                lm += len(mem)
    return carriers, lg, lm


def _r3_merge(nodes, rtl):
    """schedule_segment's R3 step (after ov_census.build_edges at depth 2):
    None below r3.  At r3: check the XWIN re-walk against build_edges, merge
    every four-channel key group into its carrier (the bank forced as the
    block comment says), and return the bookkeeping S["bcast"] carries."""
    if rtl != "r3":
        return None
    snap = _r3_edge_snapshot(nodes)
    _r3_xwin(nodes, {})
    need(_r3_edge_snapshot(nodes) == snap,
         "R3: the XWIN re-walk does not reproduce ov_census.build_edges' "
         "XWIN edges / banks (the port drifted)")
    carriers, lg, lm = _r3_groups(nodes)
    forced, xsrc = _r3_xwin(nodes, carriers)
    member = {m: car for car, mem in carriers.items() for m in mem}
    merged = set(m for m in member if member[m] != m)
    for car, mem in carriers.items():
        cn = nodes[car]
        for m in mem[1:]:
            sn = nodes[m]
            for p, k in sn.preds.items():
                q = member.get(p, p)
                if q != car:
                    cn.preds.setdefault(q, k)
            cn.sdeps |= sn.sdeps
            sn.preds, sn.sdeps = {}, set()
            sn.redundant = True
    for i, n in enumerate(nodes):
        hit = [p for p in n.preds if p in merged]
        for p in hit:
            k = n.preds.pop(p)
            if member[p] != i:
                n.preds.setdefault(member[p], k)
        need(not (n.sdeps & merged), f"R3: a stream-edge onto a MOVX at "
                                     f"{n.pc}")
    return {"carriers": carriers, "merged": merged, "forced": forced,
            "xsrc": xsrc, "unicast_left_groups": lg,
            "unicast_left_movx": lm}


def _r3_xcheck(S, start, fin, send, tau):
    """ov_census.postcheck's (x) rule for EVERY destination channel of each
    broadcast (the census's own check sees the carrier's channel only): no
    broadcast writes an XWIN bank while a stream on any channel reads that
    bank.  Raises on a violation; returns the checks made."""
    bc = S.get("bcast")
    if not bc:
        return 0
    nodes, live = S["nodes"], S["live"]
    streams = collections.defaultdict(list)
    for i, n in enumerate(nodes):
        if live[i] and n.kind == "mvgo":
            streams[n.chan].append((fin[i], send[i] + tau[i], i))
    nc, bad = 0, []
    for car in bc["carriers"]:
        n = nodes[car]
        for c in range(4):
            for (s0, s1, m) in streams[c]:
                nc += 1
                xb = nodes[m].bank[0] if nodes[m].bank else 0
                same = n.bank == -1 or xb == -1 or xb == n.bank
                if same and s0 < fin[car] and start[car] < s1:
                    bad.append(("x-bcast-on-streaming-bank", n.pc, c,
                                nodes[m].pc))
    if bad:
        raise AssertionError(f"POSTCHECK FAILED (R3, per destination): "
                             f"{len(bad)} violations, first {bad[:5]}")
    return nc


def _r3_post(S, post, start, fin, send, tau):
    """replay()'s post-check: OV1's, plus the per-destination (x) rule when
    the segment carries broadcasts (r0-r2: returned unchanged)."""
    if not S.get("bcast"):
        return post
    return (post[0], post[1] + _r3_xcheck(S, start, fin, send, tau))


def _r3_rec(S, x, rec):
    """emit_segment's record: a carrier's MOVX becomes the BROADCAST
    (flags[7:4] = 0xF; target = the bank's start word, set by banked())."""
    bc = S.get("bcast")
    if not bc or x not in bc["carriers"]:
        return rec
    need(rec.opcode == SF.OP_MOVX and not (rec.flags & 0xF),
         f"R3: carrier at {S['nodes'][x].pc} is not a direct MOVX")
    return SF.Rec(rec.opcode,
                  flags=(rec.flags & ~0xF0) | (SF.MOVX_BCAST << SF.CHAN_SHIFT),
                  target=rec.target, imm32=rec.imm32, addr_lo=rec.addr_lo,
                  len_or_addr_hi=rec.len_or_addr_hi)


def assert_bcast_consumers(recs, pairs, where="stream"):
    """B17.3 WINDOW, per destination: every (MVGO index, broadcast index) in
    `pairs` — the pass's record of which broadcast wrote the x each MVGO
    reads — must have the MVGO AFTER the broadcast and its XBANK window
    (1536 * SHAPE bit 29) equal to the broadcast's start word.  Raises
    HazardError naming both records (the model reads the other window
    silently when it holds an intact vector: task-R3-3-review.md)."""
    for (mi, bi) in pairs:
        m, b = recs[mi], recs[bi]
        if not (b.opcode == SF.OP_MOVX and b.chan == SF.MOVX_BCAST):
            raise HazardError(f"{where}: record {bi} is not a broadcast MOVX")
        if m.opcode != SF.OP_MVGO or mi < bi:
            raise HazardError(f"{where}: record {mi} is not a MVGO after the "
                              f"broadcast at record {bi}")
        xb = (m.imm32 >> 29) & 1
        w0 = b.target & SF.MOVX_WORD_MASK
        if SF.XBANK_WORD * xb != w0:
            raise HazardError(
                f"{where}: record {mi} MVGO on mv{m.chan} reads XWIN bank "
                f"{xb} (word {SF.XBANK_WORD * xb}) but its x is the broadcast "
                f"at record {bi}, window word {w0}: every consumer of a "
                f"broadcast takes its XBANK (B17.3 WINDOW)")
    return len(pairs)


def _r3_seg(rep, S, seg_items, new_lo, rtl):
    """reorder()'s per-segment R3 step (None below r3; returns None so the
    caller's seg_info row is appended): the consumer assert over the emitted
    segment, the per-destination post-check of the SCHEDULE, the counts."""
    if rtl != "r3":
        return None
    bc, nodes, live = S["bcast"], S["nodes"], S["live"]
    seg = rep["segments"][-1]
    pos = {oi: p for p, (oi, _r) in enumerate(seg_items) if oi is not None}
    pairs = [(pos[nodes[m].pc], pos[nodes[w].pc])
             for m, w in sorted(bc["xsrc"].items())
             if w in bc["carriers"] and live[m]]
    assert_bcast_consumers([r for (_oi, r) in seg_items], pairs,
                           f"segment {seg['k']}")
    rep.setdefault("bcast_consumers", []).extend(
        (new_lo + a, new_lo + b) for (a, b) in pairs)
    tau = [S["groups"][n.grp]["tau"] if n.kind == "mvgo" else 0
           for n in nodes]
    nx = _r3_xcheck(S, S["start"], S["fin"], S["send"], tau)
    seg.update({"bcast": len(bc["carriers"]),
                "siblings_merged": len(bc["merged"]),
                "forced": len(bc["forced"]),
                "unicast_left_groups": bc["unicast_left_groups"],
                "unicast_left_movx": bc["unicast_left_movx"],
                "bcast_consumers": len(pairs), "bcast_xchecks": nx})
    return None


def _r3_admit(new, rep, rtl, nbank):
    """reorder()'s R3 admission (returns nbank unchanged): an r3 stream with
    a broadcast must be REFUSED at {R1,R2} by the validator (its bank fields
    alone would pass there: R2 is not fail-closed, B17.2)."""
    if rtl != "r3":
        return nbank
    nb = sum(1 for r in new
             if r.opcode == SF.OP_MOVX and r.chan == SF.MOVX_BCAST)
    try:
        SF.validate_stream(new, caps=CAPS_OF["r2"])
        refused = False
    except SF.SeqValidationError:
        refused = True
    need(refused or not nb,
         f"an r3 stream with {nb} broadcasts validated at {{R1,R2}}")
    rep["refused_at_r1r2"] = refused
    rep["broadcasts"] = nb
    return nbank


def _r3_meta(meta, rep):
    """write_out's R3 manifest fields (informational, as the caps are);
    returns rep["refused_at_r1"] for the caller's line."""
    if rep.get("rtl") == "r3":
        need("shape_isa" in meta, "an r3 manifest must carry shape_isa "
                                  "(NEXT_SESSION.md §9 (f) rule 1)")
        sv = meta["sv1_reorder"]
        segs = rep["segments"]
        sv["broadcasts"] = rep["broadcasts"]
        sv["siblings_merged"] = sum(s["siblings_merged"] for s in segs)
        sv["forced"] = sum(s["forced"] for s in segs)
        sv["unicast_left_groups"] = sum(s["unicast_left_groups"]
                                        for s in segs)
        sv["unicast_left_movx"] = sum(s["unicast_left_movx"] for s in segs)
        sv["refused_at_r1r2"] = rep["refused_at_r1r2"]
    return rep["refused_at_r1"]


def _r3_print(rep, rtl):
    """main()'s r3 lines (the r2 block's, labelled r3, plus the broadcast
    counts); returns False (the r2 block runs only at r2)."""
    if rtl != "r3":
        return False
    segs = rep["segments"]
    body = [s for s in segs if s["body"]]
    print(f"=== r3: refused at caps ['R1', 'R2']: {rep['refused_at_r1r2']}; "
          f"at ['R1']: {rep['refused_at_r1']}; broadcasts in the stream "
          f"{rep['broadcasts']}; bank fields {rep['bank_fields']}")
    for s in segs:
        print(f"=== r3: seg{s['k']} broadcasts {s['bcast']} (siblings merged "
              f"{s['siblings_merged']}), FORCED {s['forced']}, unicast-left "
              f"groups {s['unicast_left_groups']} (MOVX "
              f"{s['unicast_left_movx']}); consumers asserted "
              f"{s['bcast_consumers']}; per-destination x checks "
              f"{s['bcast_xchecks']}")
        print(f"=== r3: seg{s['k']} banks " + ", ".join(
            f"{k} {v}" for k, v in s["banks"].items()))
    print("=== r3: CORRECTED prediction (seq_cost FENCE_REC / TAIL1 / "
          "CMD_RESID_FRAC) per segment: " + ", ".join(
              f"seg{s['k']} {s['pred_mk']}" for s in segs)
          + (f"; LOOP BODY {body[0]['pred_mk']} cyc (lane "
             f"{body[0]['pred_lane']} + CMD residual "
             f"{body[0]['pred_cmd_resid']}; classes labelled "
             f"{body[0]['pred_labelled']})" if body else ""))
    return False


def _synthetic_r3():
    """_synthetic()'s shape on four channels: matvec A (the EMB's x), matvec
    B (another source): each MOVX x4 -> one broadcast."""
    import hwmap as HW
    shape = HW.shape_word(4, 0, 1)
    recs = [SF.Rec(SF.OP_CSRWR, target=SF.CSR_SEQ_TCNT, imm32=2),
            SF.Rec(SF.OP_EMB, addr_lo=0x100, len_or_addr_hi=128)]
    for k, src in enumerate((0x100, 0x800)):
        recs += [SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), addr_lo=src,
                        len_or_addr_hi=128) for c in range(4)]
        recs += [SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                        target=SF.MVGO_NOWAIT, imm32=shape,
                        addr_lo=HW.W_BASE & 0xFFFFFFFF, len_or_addr_hi=4 << 8)
                 for c in range(4)]
        recs.append(SF.Rec(SF.OP_FENCE))
        recs += [SF.Rec(SF.OP_MOVY, flags=SF.MOVY_MODE_BIT, target=c,
                        addr_lo=0x400 + 0x40 * k + 4 * c, len_or_addr_hi=4)
                 for c in range(4)]
    recs += [SF.Rec(SF.OP_JMP, flags=SF.JMP_TCNT, imm32=1),
             SF.Rec(SF.OP_HALT)]
    dur = {SF.OP_EMB: 200, SF.OP_MOVX: 100, SF.OP_MVGO: 10,
           SF.OP_MOVY: 50, SF.OP_CSRWR: 5, SF.OP_JMP: 3}
    rows, t, ends = {}, 0, []
    for pc in range(1, len(recs) - 1):
        r = recs[pc]
        cls = [0] * 16
        if r.opcode == SF.OP_MVGO:
            cls[OC.BSY0 + r.chan] = 1000 * (r.chan + 1)
            ends.append(t + dur[r.opcode] + 1000 * (r.chan + 1))
        if r.opcode == SF.OP_FENCE:
            d = max(ends) + 40 - t
            ends = []
        else:
            d = dur[r.opcode]
        rows[pc] = (r.opcode, t, d, cls)
        t += d
    return recs, rows, []


def selftest_r3():
    """R3-5: at r3 the four-channel synthetic's two matvecs emit ONE
    broadcast each (words 1536, 0) and no unicast MOVX; every consumer's
    XBANK agrees; the output is valid at {R1,R2,R3} only (refused at
    {R1,R2}, {R1}, {}), passes the per-destination hazard assert, and
    replays no slower than r2."""
    ok = True
    for form in ("A", "B"):
        recs, rows, cps = _synthetic_r3()
        n2, _c2, r2 = reorder(recs, lambda k, lo, hi: rows, form, cps,
                              rtl="r2")
        recs, rows, cps = _synthetic_r3()
        n3, _c3, r3 = reorder(recs, lambda k, lo, hi: rows, form, cps,
                              rtl="r3")
        bx = [r.target for r in n3 if r.opcode == SF.OP_MOVX
              and r.chan == SF.MOVX_BCAST]
        ux = [r for r in n3 if r.opcode == SF.OP_MOVX
              and r.chan != SF.MOVX_BCAST]
        s2, s3 = r2["segments"][0], r3["segments"][0]
        nc = assert_bcast_consumers(n3, r3["bcast_consumers"])
        good = (bx == [SF.XBANK_WORD, 0] and not ux and nc == 8
                and r3["refused_at_r1r2"] and r3["refused_at_r1"]
                and r3["refused_at_empty"]
                and r3["caps"] == ["R1", "R2", "R3"]
                and s3["forced"] == 0 and s3["replay_mk"] <= s2["replay_mk"])
        print(f"[r3 {form}] broadcast words {bx}; unicast MOVX {len(ux)}; "
              f"consumers asserted {nc}; refused at {{R1,R2}} "
              f"{r3['refused_at_r1r2']}, {{R1}} {r3['refused_at_r1']}, {{}} "
              f"{r3['refused_at_empty']}; replay r3 {s3['replay_mk']} <= r2 "
              f"{s2['replay_mk']}; predicted {s3['pred_mk']} -> "
              f"{'PASS' if good else 'FAIL'}")
        ok &= good
    return ok


if __name__ == "__main__":
    main()
