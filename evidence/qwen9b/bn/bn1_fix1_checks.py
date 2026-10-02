#!/usr/bin/env python3
"""bn1_fix1_checks.py (v2 — v1 read the row columns one place late: lop, ncyc and the
weight-beat deltas were off by one, which its own output showed as every cell
labelled MLP and chan 3 carrying 12 beats.  The signature-histogram half — I-1,
I-2 and the state-DMA figure — was unaffected and 012 and 013 agree on it.)

ORIGINAL: bn1_fix1_checks.py — the measurements BN1's fix round 1 needs, from the
committed census CSV.  Read-only; every number printed here is used to
correct a claim in evidence/qwen9b/bn/BN_CENSUS.md."""
import collections, sys
CLS = ["L_CMP","L_DMA","MOVER","SEQBULK","MV0_STR","MV1_STR","MV2_STR","MV3_STR",
       "MV0_BSY","MV1_BSY","MV2_BSY","MV3_BSY","SMEM_RD","SMEM_WR","RECDDR","BFAB"]
CI={n:i for i,n in enumerate(CLS)}
LOP={1:"VN",2:"VNW",3:"ROPET",4:"ROPE",5:"CONVW",6:"CONV",7:"GATE",8:"DNST",
     9:"KVAP",10:"ATTN",11:"ALU",12:"DNZ",13:"SLD",14:"SST"}
csv=sys.argv[1]
rows=[]; sig=collections.defaultdict(dict)
for line in open(csv):
    if line.startswith("R,"):
        f=[int(x) for x in line.rstrip("\n").split(",")[1:]]
        rows.append(f)
    elif line.startswith("S,"):
        g=line.rstrip("\n").split(",")
        sig[int(g[1])][int(g[2])]=int(g[3])
body=[t for t in sig if t!=0]; n=len(body)
STR=sum(1<<CI["MV%d_STR"%c] for c in range(4))
BSY=sum(1<<CI["MV%d_BSY"%c] for c in range(4))
MV=1<<CI["MOVER"]; LC=1<<CI["L_CMP"]; LD=1<<CI["L_DMA"]
def cyc(pred): return sum(c for t in body for m,c in sig[t].items() if pred(m))/n
ms=lambda c: c/250000.0
print("tokens", n)
print("=== I-1: are the three model terms disjoint? ===")
lay=cyc(lambda m:m&LC); wst=cyc(lambda m:m&STR)
mwk=cyc(lambda m:(m&MV) and not (m&STR))
print("  layer            %12.1f cyc  %8.3f ms"%(lay,ms(lay)))
print("  weight streaming %12.1f cyc  %8.3f ms"%(wst,ms(wst)))
print("  mover work       %12.1f cyc  %8.3f ms"%(mwk,ms(mwk)))
print("  layer AND streaming        %.1f cyc"%cyc(lambda m:(m&LC) and (m&STR)))
print("  layer AND mover-work       %.1f cyc"%cyc(lambda m:(m&LC) and (m&MV) and not (m&STR)))
print("  streaming AND mover-work   %.1f cyc  (0 by construction)"%cyc(lambda m:(m&STR) and (m&MV) and not (m&STR)))
u3=cyc(lambda m:(m&LC) or (m&STR) or ((m&MV) and not (m&STR)))
print("  UNION of the three %12.1f cyc = %8.3f ms"%(u3,ms(u3)))
print("  SUM   of the three %12.1f cyc = %8.3f ms"%(lay+wst+mwk,ms(lay+wst+mwk)))
tok=sum(sum(sig[t].values()) for t in body)/n
print("  token              %12.1f cyc = %8.3f ms"%(tok,ms(tok)))
print("  NONE of the three  %12.1f cyc = %8.3f ms = %.2f %%"%(tok-u3,ms(tok-u3),100*(tok-u3)/tok))
print("=== I-2: the overlap the model's m stands for ===")
o1=cyc(lambda m:(m&MV) and not (m&STR) and (m&BSY))
o2=cyc(lambda m:(m&MV) and (m&STR))
print("  mover work WHILE any matvec engine busy  %10.1f cyc = %.4f %% of the token"%(o1,100*o1/tok))
print("  mover busy WHILE any channel streams     %10.1f cyc (the FENCE wait)"%o2)
print("  -> measured m = 1 - overlap/counted = %.5f"%(1-o1/(mwk if mwk else 1)))
print("=== §7 / M-8: the label partition and the GQA per-layer division ===")
cuts=collections.defaultdict(list)
for i,r in enumerate(rows):
    if r[3]==1 and r[5]==0x0030: cuts[r[1]].append(i)
tot=collections.Counter(); cells=collections.Counter(); runs=collections.Counter()
mixed=collections.Counter(); ropet_in_run=[]
for t in sorted(cuts):
    if t==0: continue
    end=max(i for i,r in enumerate(rows) if r[1]==t)
    b=cuts[t]+[end+1]; lab=[]
    for k in range(len(cuts[t])):
        lo,hi=b[k],b[k+1]
        ops={rows[j][6] for j in range(lo,hi) if rows[j][6]>=0}
        amax=any(rows[j][3]==7 for j in range(lo,hi))
        L="HEAD" if amax else "DN" if (8 in ops or 12 in ops) else \
          "GQA" if ops&{3,4,9,10} else "MLP" if ops else "-"
        if L=="DN" and (ops&{3,4,9,10}): mixed["DN cell also holds GQA ops"]+=1
        if L=="GQA" and (8 in ops or 12 in ops): mixed["GQA cell also holds DNST"]+=1
        lab.append((L,lo,hi-1))
        cells[L]+=1
        tot[L]+=sum(rows[j][8] for j in range(lo,hi))
    # maximal runs of equal label, and the ROPET count inside each GQA run
    prev=None; cur=[]
    for L,lo,hi in lab:
        if L!=prev:
            if prev is not None: runs[prev]+=1
            if prev=="GQA": ropet_in_run.append(curR)
            cur=[]; curR=0
        if L=="GQA":
            curR+=sum(1 for j in range(lo,hi+1) if rows[j][3]==2 and rows[j][6]==3)
        prev=L
    runs[prev]+=1
    if prev=="GQA": ropet_in_run.append(curR)
print("  cells/token", {k:v/n for k,v in cells.items()})
print("  maximal RUNS of equal label per token", {k:v/n for k,v in runs.items()})
print("  ROPET commands inside each GQA run:", ropet_in_run[:16], "... distinct:", sorted(set(ropet_in_run)))
print("  label purity violations:", dict(mixed) or "NONE")
s=0
for k in tot:
    print("  %-5s %12.1f cyc/token = %8.3f ms"%(k,tot[k]/n,ms(tot[k]/n))); s+=tot[k]/n
print("  labelled total %12.1f  token %12.1f  remainder %.1f cyc (%.4f %%)"%(s,tok,tok-s,100*(tok-s)/tok))
print("=== RC-1: per-LAYER-OPCODE, LANE cycles vs RECORD-WINDOW cycles ===")
print("  The `lop` column names the layer opcode in flight during a record's")
print("  window.  Two different quantities can be summed against it and they")
print("  are NOT interchangeable:")
print("    L_CMP  = the compute LANE's own busy cycles inside the window")
print("             (class 0).  Summed over every lop this is the whole lane,")
print("             which is what S4 §5.3.2's per-opcode table and this")
print("             census's 41.610 ms both are, so it is the comparable one.")
print("    ncyc   = the record window itself, dispatch to the next record.")
print("             It includes the sequencer's poll/fetch either side, so it")
print("             is LARGER and is not a lane figure.")
lane=collections.Counter(); win=collections.Counter(); cmds=collections.Counter()
for r in rows:
    if r[1]==0: continue
    lane[r[6]]+=r[9]; win[r[6]]+=r[8]
    if r[3]==2: cmds[r[6]]+=1
print("  %-6s %10s %14s %10s %14s %10s"%("lop","cmds/tok","LANE cyc/tok","LANE ms","WINDOW cyc/tok","WINDOW ms"))
tl=tw=0
for k in sorted(lane, key=lambda k:-lane[k]):
    print("  %-6s %10.1f %14.1f %10.3f %14.1f %10.3f"%(
        LOP.get(k,"(none)"),cmds[k]/n,lane[k]/n,ms(lane[k]/n),win[k]/n,ms(win[k]/n)))
    tl+=lane[k]/n; tw+=win[k]/n
print("  %-6s %10.1f %14.1f %10.3f %14.1f %10.3f"%("TOTAL",sum(cmds.values())/n,tl,ms(tl),tw,ms(tw)))
print("  -> the LANE column totals %.3f ms = the L_CMP class of BN_CENSUS §4."%ms(tl))
print("  RC-1 attribution, like for like against S4 §5.3.2's .txt table")
print("  (ALU 6,219 cmds / 22.646 ms, VN 1,761 / 4.371 ms):")
alu=ms(lane[11]/n); vn=ms(lane[1]/n)
print("    ALU  %.3f - 22.646 = %+.3f ms"%(alu,alu-22.646))
print("    VN   %.3f -  4.371 = %+.3f ms"%(vn,vn-4.371))
print("    net  %+.3f ms against the 45.674 - 41.610 = 4.064 ms gap = %.0f %%"%(
    (alu-22.646)+(vn-4.371), 100*abs((alu-22.646)+(vn-4.371))/4.064))
print("    ALU as a share of this census's 41.610 ms lane: %.1f %%"%(100*alu/41.610))
print("    SLD busy_cmp (the F2 queue-full hold): %.1f cyc/token"%(lane[13]/n))
print("=== M-9: the channel-rebalanced bound ===")
wb=[0]*4
for r in rows:
    if r[1]==0: continue
    for c in range(4): wb[c]+=r[25+c]
strc=[cyc(lambda m,c=c: m&(1<<CI["MV%d_STR"%c])) for c in range(4)]
tot_b=sum(wb)/n
print("  beats/token per chan", [round(x/n) for x in wb], " total %.0f"%tot_b)
print("  if the four channels were perfectly even: %.0f beats each"%(tot_b/4))
rate=(wb[0]/n)/strc[0]
print("  at the measured %.4f beats/cyc -> %.1f cyc = %.3f ms"%(rate,tot_b/4/rate,ms(tot_b/4/rate)))
res=cyc(lambda m:m==0)
print("  floor with rebalance = %.3f + %.3f = %.3f ms -> %.2fx"%(ms(tot_b/4/rate),ms(res),ms(tot_b/4/rate+res),tok/(tot_b/4/rate+res)))
print("=== R10/#6: state-DMA with no other class ===")
print("  L_DMA and nothing else: %.1f cyc/token"%cyc(lambda m:m==LD))
