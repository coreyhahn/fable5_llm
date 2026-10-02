"""Board-free: what chat_seq/seq_chat carry today, and what the 9B stream
derives.  FABLE5_MODEL is read from the environment; run once unset and once
=9b.  No board, no lock, no DMA."""
import json, os, sys
sys.path.insert(0, "sw"); sys.path.insert(0, "ref")
import seq_chat as SC, hwmap as HW, seq_format as SF
import chat_seq as CS

sel = os.environ.get("FABLE5_MODEL", "unset")
print(f"=== FABLE5_MODEL={sel}")
print("--- ref/seq_chat.py, the compiler of record (frozen vs derived)")
print(f"  DEFAULT_PREFIX        {os.path.relpath(SC.DEFAULT_PREFIX)}")
print(f"  TEMPLATE_NREC         {SC.TEMPLATE_NREC}   (FROZEN)")
print(f"  TEMPLATE_SHA256       {SC.TEMPLATE_SHA256[:16]}   (FROZEN)")
print(f"  SEQDATA_SHA256        {SC.SEQDATA_SHA256[:16]}   (FROZEN)")
print(f"  CONST_BYTES           {SC.CONST_BYTES}   (FROZEN — the 0.8B/2B const region)")
print(f"  R_PREAMBLE/BODY_FULL  {SC.R_PREAMBLE} / {SC.R_BODY_FULL}   (FROZEN)")
print(f"  R_BODY_LITE/TCNT/HALT {SC.R_BODY_LITE} / {SC.R_TCNT} / {SC.R_HALT}   (FROZEN)")
print(f"  POS_COPIES            {SC.POS_COPIES}   (DERIVED from layer_types)")
print(f"  POS_WORDS/COPY_BYTES  {SC.POS_WORDS} / {SC.POS_COPY_BYTES}   (DERIVED)")
print(f"  POS_STRIDE            {SC.POS_STRIDE} B/position   (DERIVED)")
print(f"  POS_LDC_REC_OFFSETS   {SC.POS_LDC_REC_OFFSETS}   (FROZEN, 6 entries)")
print(f"  T_MAX                 {SC.T_MAX}   (FROZEN)")
print(f"  XRF_POS_MAX           {SC.XRF_POS_MAX}   (DERIVED: signed 18-bit XRF[4] / POS_STRIDE)")
print("--- sw/chat_seq.py, the host twin")
print(f"  TEMPLATE_PREFIX       {os.path.relpath(CS.TEMPLATE_PREFIX)}  nrec {CS.TEMPLATE_NREC}  isa v{CS.TEMPLATE_ISA_VERSION}")
print(f"  TEMPLATE4_PREFIX      {os.path.relpath(CS.TEMPLATE4_PREFIX)}  nrec {CS.TEMPLATE4_NREC}")
print(f"  TEMPLATE4_SHA256      {CS.TEMPLATE4_SHA256[:16]}   (the nch=4 gate)")
print(f"  POS_COPIES/POS_STRIDE {CS.POS_COPIES} / {CS.POS_STRIDE}")
print(f"  T_MAX / POSBLOB_BYTES {CS.T_MAX} / {CS.POSBLOB_BYTES} B")
print(f"  the same blob at T=4096: {4096 * CS.POS_STRIDE} B "
      f"({4096 * CS.POS_STRIDE / 1048576.0:.1f} MiB)")
print(f"  sw/hwmap.STATE_T_MAX  {HW.STATE_T_MAX}   (the HARDWARE ceiling)")

print("\n--- what derive_geometry() reads OUT OF the 9B stream (nch=4 path)")
p = "tb/scripts/w9/model_9b_s1.e4"
recs0 = SF.unpack_stream(open(p + ".seq", "rb").read())
meta0 = json.load(open(p + ".seq.json"))
try:
    g = CS.derive_geometry(recs0, meta0)
except Exception as e:
    print(f"  REFUSED: {type(e).__name__}: {e}")
else:
    for k in sorted(g):
        if not k.startswith("_"):
            v = g[k]
            print(f"  {k:22s} {v}")
    print(f"  => the nch=4 path DERIVES all of it; the frozen slices above "
          f"belong to the nch=1 path only")
