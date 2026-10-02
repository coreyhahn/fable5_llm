#!/usr/bin/env python3
"""sd1_common.py — shared decoding for Task SD1 (the .txt-vs-.e4 schedule delta).

READ-ONLY over the artifacts: it opens `tb/scripts/w9/model_9b_s1.txt` and
`tb/scripts/w9/model_9b_s1.e4.seq` and decodes them with the repo's OWN
decoders (`ref/seq_format.py`, `ref/gen_layer_script.py`), so the command
classification here is the emitter's, not a re-derivation.  Nothing under
ref/, rtl/ or tb/ is modified; nothing is written but stdout.

A layer command is keyed as
    ("ALU", <sub-op name>, n [, "probe"])      command 11
    ("VN",  <mode name>, n)                     command 1
    (<layer op name>,)                          everything else
where the ALU sub-op / VN mode / count are read out of ARG0/ARG2 exactly as
`ref/seq_format.SeqEmitter._cmd` packs them.

Run with FABLE5_MODEL=9b (the geometry import needs the model selection).
"""
import hashlib
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "ref"))

import seq_format as SF            # noqa: E402
import gen_layer_script as GLS     # noqa: E402
import layer_ref as LR             # noqa: E402

BASE = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1")
TXT = BASE + ".txt"
SEQ = BASE + ".e4.seq"
SEQJSON = BASE + ".e4.seq.json"

# layer_chan command numbers (docs/SEQ_ISA.md B7; the census's `op` column)
LOP_NAME = {1: "VN", 2: "VNW", 3: "ROPET", 4: "ROPE", 5: "CONVW",
            6: "CONV", 7: "GATE", 8: "DNST", 9: "KVAP", 10: "ATTN",
            11: "ALU", 12: "DNZ", 13: "SLD", 14: "SST"}
ALU_NAME = {0: "DYNQ8", 1: "SHIFT32", 2: "SCALE", 3: "EMUL", 4: "ADD",
            5: "SILU16", 6: "SILU32", 7: "SIGM16", 8: "EMUL32",
            9: "SHIFT32W", 10: "AMAX32", 12: "DYNQ16"}
VN_NAME = {0: "rmsnorm0", 1: "rmsnorm1", 2: "l2norm", 3: "mode3"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def key_of(op, a0, a1, a2):
    """The class of one layer command, from its four words."""
    if op == 11:
        sub = a0 & 0xF
        n = GLS.dec_alu_len(a0)
        p0 = GLS.dec_alu_p0(a0, a2)
        k = ("ALU", ALU_NAME.get(sub, f"sub{sub}"), n)
        if sub == 8 and (p0 & SF.ALU_PROBE_BIT) and p0 < (1 << 16):
            k = k + ("probe",)
        return k
    if op == 1:
        mode = a0 & 0x3
        n = 1 << ((a0 >> 2) & 0xF)
        name = VN_NAME[mode]
        if mode == SF.VN_EPSNORM_MODE and (a2 & SF.VN_ARG2_EPS):
            name = "EPS-NORM"
        return ("VN", name, n)
    return (LOP_NAME.get(op, f"op{op}"),)


def txt_steps(path=TXT):
    """Walk the .txt: yield (step, lineno, op, a0, a1, a2) for every C record.

    Step 0 is everything before the first `M` (embed) record; step s >= 1
    starts at the s-th `M` record — the same boundary the layer census's
    per-step table uses (its step 0 = the 2-command preamble)."""
    step = 0
    with open(path, "rb") as f:
        for ln, line in enumerate(f, 1):
            c = line[:1]
            if c == b"C":
                _, op, a0, a1, a2 = line.split()
                yield (step, ln, int(op, 16), int(a0, 16), int(a1, 16),
                       int(a2, 16))
            elif c == b"M":
                step += 1


def seq_records(path=SEQ):
    with open(path, "rb") as f:
        return SF.unpack_stream(f.read())


def seq_cmds(recs):
    """Walk the .e4 stream in STATIC record order: yield
    (body, cmd_rec_index, op, a0, a1, a2) for every CMD record.

    `body` 0 is the launch preamble (before the first EMB); body b >= 1
    begins at the b-th EMB record.  The stream holds FOUR written-out
    bodies; the fourth is the TCNT_SEQ=3 loop body (tb/seq_timeline.svh
    header), so per-TOKEN counts are per-body counts and the loop body
    runs for tokens 4, 5 and 6."""
    arg = {SF.CSR_L_ARG0: 0, SF.CSR_L_ARG1: 0, SF.CSR_L_ARG2: 0}
    body = 0
    for i, r in enumerate(recs):
        if r.opcode == SF.OP_EMB:
            body += 1
        elif r.opcode == SF.OP_CSRWR and r.target in arg:
            arg[r.target] = r.imm32
        elif r.opcode == SF.OP_CMD:
            yield (body, i, r.imm32 & 0xFF, arg[SF.CSR_L_ARG0],
                   arg[SF.CSR_L_ARG1], arg[SF.CSR_L_ARG2])
