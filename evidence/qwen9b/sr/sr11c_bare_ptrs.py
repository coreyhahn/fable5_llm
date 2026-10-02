#!/usr/bin/env python3
"""sr11c_bare_ptrs.py — SR11c fix round 1 (review I2): docs/SEQ_ISA.md's BARE
RTL pointers (`seq_unit.sv:NNN` / `seq_movers.sv:NNN`, written without the
rtl/ prefix, so neither o3_cite_drift.py nor spec_cites.py sees them).

THE PROOF, per pointer number (o3's own line map, imported):
  1. C0 = the commit that introduced the pointer's exact text into SEQ_ISA
     (`git log -S<snippet> --reverse`, first hit) — the pointer is taken to be
     in C0's coordinates, as o3 takes a document to be at its --base;
  2. the ANCHOR (a substring of the code the ISA sentence names) is within
     W lines of the number in rtl/<file>@C0 — so the pointer was RIGHT when
     written (W = 2 for a single line; a range must contain it);
  3. N* = line_map(rtl/<file>@C0 -> the working file); None (rewritten) is
     NOT provable;
  4. the anchor is within W lines of N* (or inside the mapped range) at HEAD.
Only the digits change and the bare form is kept (adding rtl/ is claim text,
SR9's call).  --check prints every proof and landing; --apply rewrites the
proven numbers on their SEQ_ISA line (utf-8, digits only) and nothing else.
  sr11c_bare_ptrs.py --check | --apply
"""
import importlib.util
import os
import re
import subprocess
import sys

REPO = "/home/cah/r2d2/code/fpga/fable5_llm"
DOC = "docs/SEQ_ISA.md"
spec = importlib.util.spec_from_file_location(
    "o3", os.path.join(REPO, "evidence/qwen9b/o3/o3_cite_drift.py"))
o3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o3)

# (SEQ_ISA line, rtl file, the pointer text as it reads now (the -S snippet;
#  its numbers, in order, are the ones mapped), anchor, what the ISA says)
P = [
 (268, "seq_unit.sv", "seq_unit.sv:1420)", "DEAD_C0DE", "reads outside the map return 0xDEADC0DE"),
 (277, "seq_unit.sv", "seq_unit.sv:905-913,", "if (start", "what a START does not clear"),
 # fix round 2 (NEW-I1): the continuation on the next line
 (278, "seq_unit.sv", "reset block at :856-876", "rstn", "verified against the reset block"),
 (291, "seq_unit.sv", "seq_unit.sv:1218, `abort_req`", "abort_req", "ABORT is CTRL bit 1"),
 (295, "seq_unit.sv", "seq_unit.sv:925, in I_FETCH at :924", "abort_req", "ABORT is tested at a record boundary, in I_FETCH"),
 (299, "seq_unit.sv", "seq_unit.sv:1392-1393", "of_ovf", "STATUS bit layout"),
 (314, "seq_unit.sv", "seq_unit.sv:318, `OF_DEPTH`", "OF_DEPTH", "OUT FIFO depth 64"),
 (318, "seq_unit.sv", "(seq_unit.sv:320-322)", "of_", "the OUT FIFO"),
 (324, "seq_unit.sv", "seq_unit.sv:1161-1164", "of_ovf", "push when full sets the sticky of_ovf"),
 (331, "seq_unit.sv", "seq_unit.sv:1406)", "csr_of_pop", "csr_of_pop <= (of_cnt != 0)"),
 (345, "seq_unit.sv", "seq_unit.sv:696-751", "v_bad", "the decode validator"),
 (349, "seq_unit.sv", "seq_unit.sv:826-832, `csr_addr`", "csr_addr", "csr_id spaces, csr_addr"),
 (361, "seq_unit.sv", "seq_unit.sv:964-968", "L_ARG", "ARG0/1/2 shadow"),
 (373, "seq_movers.sv", "(seq_movers.sv:517)", "x_wwords", "ragged tail zero-padded"),
 (383, "seq_movers.sv", "seq_movers.sv:437-449,", "rshr64s", "MOVY dequant (rshr64s + round), then clip"),
 (384, "seq_movers.sv", "            465-480) —", "clip_out", "the clip to int16 / int32 (clip_out)"),
 (391, "seq_unit.sv", "seq_unit.sv:988-996)", "MVGO", "MVGO dispatch"),
 (413, "seq_unit.sv", "seq_unit.sv:1041-", "OP_JMP", "JMP taken iff pre-decrement TCNT_SEQ != 1 (range start)"),
 (414, "seq_unit.sv", "            1053). HAZARD", "I_FETCH", "the same range's end, on the next line"),
 (426, "seq_unit.sv", "seq_unit.sv:844-847)", "IND_", "per the indirection code"),
 (446, "seq_unit.sv", "seq_unit.sv:656-659)", "xrf", "the XRF index for everything else"),
 (449, "seq_unit.sv", "seq_unit.sv:335-339, xrf_rd", "xrf_rd", "xrf_rd"),
 (453, "seq_unit.sv", "seq_unit.sv:1055-1057)", "xrf", "the asymmetric bound"),
 (461, "seq_unit.sv", "seq_unit.sv:1241-1242)", "xrf", "host XRF seeding must go in-stream"),
 (467, "seq_unit.sv", "seq_unit.sv:107-111, 820-823)", ["sniff", "cmd_wr"], "the XRF sideband"),
 # fix round 2 (NEW-m1): the other bare RTL pointers in SEQ_ISA
 (450, "layer_chan.sv", "layer_chan.sv:44-47 says", "UNSIGNED", "layer_chan says XRF[3] is unsigned in its XRFD window"),
 (597, "layer_chan.sv", "layer_chan.sv:556-580, 729-736, 747-748", ["TOPK-32", "TK_IDENT", "tk_ptr_we"], "TOPK-32: the block, its CSR reads, the PTR write"),
 (602, "vec_alu.sv", "vec_alu.sv:425-426)", "topk_bun", "the TOPK feed bundle at the AMAX32 compare site"),
]
NUM = re.compile(r"\d+")


def git(*a):
    return subprocess.run(["git"] + list(a), cwd=REPO, capture_output=True,
                          text=True).stdout


def rng(nums):
    """snippet numbers -> [(a, b)] pointer ranges (a single line has b=a)."""
    return nums


def parse(snippet):
    """the snippet's pointer numbers as [(a, b)], in order."""
    s = snippet.split(".sv:", 1)[-1] if ".sv:" in snippet else snippet
    out = []
    for m in re.finditer(r"(\d+)(?:-(\d+))?", s):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else None
        out.append((a, b))
    return out


def has(lines, a, b, anchor, w):
    lo = max(1, a - w)
    hi = min(len(lines), (b if b else a) + w)
    return any(anchor in lines[i - 1] for i in range(lo, hi + 1))


def main():
    apply = "--apply" in sys.argv
    with open(os.path.join(REPO, DOC), encoding="utf-8") as f:
        doc = f.read().split("\n")
    proven = unproven = 0
    edits = []
    # fix round 2: --lines a,b,c restricts the run to those SEQ_ISA lines (the
    # fix-round-1 entries are applied; their snippets no longer read as listed)
    only = None
    if "--lines" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--lines") + 1].split(",")}
    for ln, fn, snip, anchor, what in P:
        if only is not None and ln not in only:
            continue
        cur = doc[ln - 1]
        if snip not in cur:
            print("  MISSING  SEQ_ISA:%d  %r not on the line" % (ln, snip))
            unproven += 1
            continue
        F = "rtl/" + fn
        c0 = git("log", "--reverse", "--format=%h", "-S", snip, "--",
                 DOC).split()
        c0 = c0[0] if c0 else None
        if c0 is None:
            print("  NOC0     SEQ_ISA:%d  %r" % (ln, snip))
            unproven += 1
            continue
        f0 = git("show", "%s:%s" % (c0, F)).split("\n")
        head = (o3.work_text(F) or "").split("\n")
        mp = o3.line_map(f0, head)
        new = snip
        print("  SEQ_ISA:%d  %s  [%s]  C0 %s  anchor %r" % (ln, snip.strip(),
                                                           what, c0, anchor))
        ok_all = True
        parts = []
        for k, (a, b) in enumerate(parse(snip)):
            anc = anchor[k] if isinstance(anchor, list) else anchor
            w = 2 if b is None else 0
            right0 = has(f0, a, b, anc, w)
            na = mp.get(a)
            nb = mp.get(b) if b else None
            c0txt = f0[a - 1].strip()[:60] if 0 < a <= len(f0) else "<EOF>"
            if not right0:
                print("      %s  BORN STALE at %s: :%d reads %r" % (
                    "%d-%d" % (a, b) if b else a, c0, a, c0txt))
                ok_all = False
                continue
            if na is None or (b and nb is None):
                print("      %s  REWRITTEN since %s (map None): :%d read %r"
                      % ("%d-%d" % (a, b) if b else a, c0, a, c0txt))
                ok_all = False
                continue
            if not has(head, na, nb, anc, w):
                print("      %s -> %s  anchor NOT at HEAD" % (a, na))
                ok_all = False
                continue
            htxt = head[na - 1].strip()[:70]
            print("      %s -> %s   C0 :%d %r | HEAD :%d %r%s" % (
                "%d-%d" % (a, b) if b else a,
                "%d-%d" % (na, nb) if b else na, a, c0txt, na, htxt,
                (" .. :%d %r" % (nb, head[nb - 1].strip()[:50])) if b else ""))
            parts.append(((a, b), (na, nb)))
        if ok_all and parts:
            it = iter([x for (_o, (na, nb)) in parts
                       for x in ([na, nb] if nb else [na])])
            new = NUM.sub(lambda _m: str(next(it)), snip)
            if new != snip:
                edits.append((ln, snip, new))
            proven += 1
            print("      PROVEN  %r -> %r" % (snip.strip(), new.strip()))
        else:
            unproven += 1
            print("      NOT PROVABLE (SR9)")
    if apply:
        for ln, s, n in edits:
            doc[ln - 1] = doc[ln - 1].replace(s, n, 1)
        with open(os.path.join(REPO, DOC), "w", encoding="utf-8") as f:
            f.write("\n".join(doc))
    print("SR11C_BARE_PTRS %s: %d pointer(s) proven (%d to rewrite), %d not "
          "provable" % ("APPLIED" if apply else "CHECK", proven, len(edits),
                        unproven))


if __name__ == "__main__":
    main()
