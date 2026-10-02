#!/usr/bin/python3
"""Pack the raw Vivado placement dump into placement.json + REPORT.txt.
Standard library only. Run on snoke from this directory."""
import base64, collections, datetime, json, os, re, statistics, struct, sys

D = os.path.dirname(os.path.abspath(__file__))
REPO_REL_DCP = "synth/out_build_046_r3_incr/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp"
TYPES = ["CLB", "DSP", "BRAM", "URAM", "IO", "GT", "CLK", "OTHER"]
KEYS = ["other", "ddr4_0", "ddr4_1", "ddr4_2", "ddr4_3", "mvchan_0", "mvchan_1", "mvchan_2",
        "mvchan_3", "dn_step", "attn_core", "state_dma", "layer_rest", "seq_0", "xdma_0",
        "axi_smc", "smc_ch0", "smc_ch1", "smc_ch2", "smc_ch3", "ctl_fabric"]
LAYER_SUB = {"u_dn": 9, "u_attn": 10, "u_dma": 11}
LAYER_PATHS = {9: "bd_i/layer_0/inst/u_core/u_dn", 10: "bd_i/layer_0/inst/u_core/u_attn",
               11: "bd_i/layer_0/inst/u_core/u_dma"}
REPORT_LUTS = {9: 42012, 10: 36639, 11: 17299}
TOP = {"ddr4_0": 1, "ddr4_1": 2, "ddr4_2": 3, "ddr4_3": 4, "mvchan_0": 5, "mvchan_1": 6,
       "mvchan_2": 7, "mvchan_3": 8, "seq_0": 13, "xdma_0": 14, "axi_smc": 15, "smc_ch0": 16,
       "smc_ch1": 17, "smc_ch2": 18, "smc_ch3": 19, "axil_smc": 20, "burst_smc": 20}


def block_of(name):
    p = name.split("/")
    if len(p) < 2 or p[0] != "bd_i":
        return 0
    b = p[1]
    if b == "layer_0":
        if len(p) > 4 and p[2] == "inst" and p[3] == "u_core" and p[4] in LAYER_SUB:
            return LAYER_SUB[p[4]]
        return 12
    if b in TOP:
        return TOP[b]
    if re.fullmatch(r"(axil_slice|burst_slice)_\d+", b):
        return 20
    return 0


IO_PAT = re.compile(r"IOB|HPIO|HRIO|HDIO|BITSLICE|RIU_OR|XIPHY|IOBDIFF|HPIOBDIFF|IOB_VREF|VREF")
GT_PAT = re.compile(r"^(GTYE4|GTHE4|GTYE3|GTHE3|PCIE40E4|PCIE4|PCIE_|CMAC|ILKN)")


def category(stype):
    if stype in ("SLICEL", "SLICEM"):
        return 0
    if stype.startswith("DSP48E2"):
        return 1
    if stype.startswith(("RAMB36", "RAMB18", "RAMBFIFO", "RAMB180", "RAMB181")):
        return 2
    if stype == "URAM288":
        return 3
    if stype.startswith(("BUFG", "MMCM", "PLL", "BUFCE")):
        return 6
    if GT_PAT.search(stype):
        return 5
    if IO_PAT.search(stype):
        return 4
    return 7


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def median_gap(vals):
    v = sorted(set(vals))
    g = [b - a for a, b in zip(v, v[1:])]
    return statistics.median(g) if g else None


def main():
    meta = dict(l.rstrip("\n").split("\t", 1) for l in open(os.path.join(D, "meta.tsv")))
    # ---- sites
    sites = {}
    type_hist = collections.Counter()
    bad_rpm = []
    for line in open(os.path.join(D, "sites.tsv")):
        f = line.rstrip("\n").split("\t")
        name, stype, rx, ry = f[0], f[1], f[2], f[3]
        cr = f[4] if len(f) > 4 else ""
        try:
            x, y = int(rx), int(ry)
        except ValueError:
            x = y = None
        cat = category(stype)
        type_hist[(stype, cat)] += 1
        if x is not None and not (0 <= x <= 65535 and 0 <= y <= 65535):
            bad_rpm.append((name, x, y))
        sites[name] = [stype, x, y, cr, cat, None]
    slr_method = {}
    for line in open(os.path.join(D, "slr.tsv")):
        n, s = line.rstrip("\n").split("\t")
        if n in sites:
            sites[n][5] = s
    no_slr = sum(1 for v in sites.values() if v[5] is None)

    # ---- cells
    site_blocks = collections.defaultdict(collections.Counter)
    block_cells = collections.Counter()
    block_luts = collections.Counter()
    block_prims = collections.defaultdict(collections.Counter)
    ref_counter = collections.Counter()
    loc_missing = collections.Counter()
    ncells_total = 0
    block_members = collections.defaultdict(set)  # block -> sites holding >=1 of its cells
    for line in open(os.path.join(D, "cells.tsv")):
        f = line.rstrip("\n").split("\t")
        if len(f) != 3:
            continue
        name, ref, loc = f
        ncells_total += 1
        b = block_of(name)
        block_cells[b] += 1
        if ref.startswith("LUT"):
            block_luts[b] += 1
        ref_counter[ref] += 1
        if loc not in sites:
            loc_missing[loc] += 1
            continue
        site_blocks[loc][b] += 1
        block_members[b].add(loc)
    noloc = [l.rstrip("\n").split("\t") for l in open(os.path.join(D, "noloc_cells.tsv")) if l.strip()]

    # ---- used sites
    used = []
    shared = 0
    shared_examples = collections.Counter()
    block_sites = collections.defaultdict(list)
    for loc, cnt in site_blocks.items():
        stype, x, y, cr, cat, slr = sites[loc]
        if x is None:
            sys.exit("STOP: used site %s has no RPM" % loc)
        top = max(cnt.values())
        tied = sorted(b for b, c in cnt.items() if c == top)
        nz = [b for b in tied if b != 0]
        owner = nz[0] if nz else 0
        if len(cnt) > 1:
            shared += 1
            shared_examples[(TYPES[cat], tuple(sorted(KEYS[b] for b in cnt)))] += 1
        n = sum(cnt.values())
        used.append((owner, cat, y, x, min(n, 255), loc))
        block_sites[owner].append((cat, x, y, slr, loc))
    if bad_rpm:
        sys.exit("STOP: RPM out of uint16 range: %r" % bad_rpm[:10])
    used.sort()
    buf = bytearray()
    for owner, cat, y, x, n, _ in used:
        buf += struct.pack("<HHBBB", x, y, cat, owner, n)

    # ---- extents / columns / pitch
    dev = [v for v in sites.values() if v[4] <= 5 and v[1] is not None]
    ext_x = [min(v[1] for v in dev), max(v[1] for v in dev)]
    ext_y = [min(v[2] for v in dev), max(v[2] for v in dev)]
    slr_names = sorted({v[5] for v in sites.values() if v[5]})
    slr_ranges = []
    for s in slr_names:
        ys = [v[2] for v in sites.values() if v[5] == s and v[4] == 0]
        slr_ranges.append({"name": s, "y": [min(ys), max(ys)]})
    columns = {}
    for ci, cname in enumerate(TYPES[:6]):
        columns[cname] = sorted({v[1] for v in sites.values() if v[4] == ci and v[1] is not None})
    def ys(ci):
        return [v[2] for v in sites.values() if v[4] == ci and v[2] is not None]
    pitch = {"CLB": {"dx": median_gap(columns["CLB"]), "dy": median_gap(ys(0))},
             "DSP": {"dy": median_gap(ys(1))}, "BRAM": {"dy": median_gap(ys(2))},
             "URAM": {"dy": median_gap(ys(3))}}
    # extra (beyond spec): mean site spacing WITHIN a column, gaps > 64 (holes) excluded
    for ci, cname in enumerate(TYPES[:4]):
        percol = collections.defaultdict(set)
        for v in sites.values():
            if v[4] == ci and v[1] is not None:
                percol[v[1]].add(v[2])
        g = []
        for yy in percol.values():
            yy = sorted(yy)
            g += [b - a for a, b in zip(yy, yy[1:]) if b - a <= 64]
        pitch[cname]["dy_mean"] = round(sum(g) / len(g), 3)

    blocks = [{"id": i, "key": KEYS[i], "cells": block_cells[i], "sites": len(block_sites[i])}
              for i in range(21)]
    out = {
        "meta": {"build": "build_046_r3_incr", "checkpoint": REPO_REL_DCP, "part": meta["PART"],
                 "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")},
        "extent": {"x": ext_x, "y": ext_y},
        "slr": slr_ranges,
        "types": TYPES,
        "blocks": blocks,
        "used": {"count": len(used), "stride": 7, "b64": base64.b64encode(bytes(buf)).decode()},
        "columns": columns,
        "pitch": pitch,
    }
    jp = os.path.join(D, "placement.json")
    with open(jp, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))

    # ---- report
    R = []
    w = R.append
    w("== Totals cross-check (used sites from LOC vs utilization.rpt) ==")
    by_cat = collections.Counter(u[1] for u in used)
    ramb36 = sum(1 for u in used if u[5].startswith("RAMB36_"))
    ramb18 = sum(1 for u in used if u[5].startswith("RAMB18_"))
    ramb36c = ref_counter["RAMB36E2"] + ref_counter["FIFO36E2"]
    ramb18c = ref_counter["RAMB18E2"] + ref_counter["FIFO18E2"]
    for lab, got, exp in [("CLB (used SLICEL/M sites)", by_cat[0], 66656), ("DSP48E2 sites", by_cat[1], 1860),
                          ("URAM288 sites", by_cat[3], 182), ("RAMB36 sites", ramb36, 245),
                          ("RAMB18 sites", ramb18, 12)]:
        w("  %-28s %7d   report %7d   %s" % (lab, got, exp, "OK" if got == exp else "MISMATCH (%+d)" % (got - exp)))
    w("  cell-level: RAMB36E2+FIFO36E2 cells %d, RAMB18E2+FIFO18E2 cells %d, DSP48E2 cells %d, URAM288 cells %d"
      % (ramb36c, ramb18c, ref_counter["DSP48E2"], ref_counter["URAM288"]))
    w("  placed leaf cells %d; primitive cells with no LOC %d; used sites %d (all categories)"
      % (ncells_total, len(noloc), len(used)))
    w("  SLR split: URAM %s ; DSP %s" % (
        dict(collections.Counter(sites[u[5]][5] for u in used if u[1] == 3)),
        dict(collections.Counter(sites[u[5]][5] for u in used if u[1] == 1))))
    w("  SLR split CLB %s (report SLR0 30472 / SLR1 32584 / SLR2 3600)" %
      dict(sorted(collections.Counter(sites[u[5]][5] for u in used if u[1] == 0).items())))
    if loc_missing:
        w("  WARNING: %d cells had a LOC not in the site list: %s" % (sum(loc_missing.values()), list(loc_missing.items())[:5]))
    if no_slr:
        w("  sites with no SLR assignment: %d" % no_slr)
    w("")
    w("== Layer sub-block instance paths (utilization_hier.rpt Total LUTs) ==")
    for i in (9, 10, 11):
        w("  %-10s %-36s report LUTs %6d   (LUT* leaf cells in dump: %d)" % (KEYS[i], LAYER_PATHS[i], REPORT_LUTS[i], block_luts[i]))
    w("")
    w("== Per-block table (sites = used sites owned by the block) ==")
    w("  RPM units. cat columns: CLB DSP BRAM URAM IO GT CLK OTHER. bbox = 5th-95th percentile.")
    for i in range(21):
        bs = block_sites[i]
        cats = collections.Counter(c for c, *_ in bs)
        slrs = collections.Counter(s for *_, s, _ in bs)
        if bs:
            xs = [x for _, x, _, _, _ in bs]; yv = [y for _, _, y, _, _ in bs]
            cen = "(%.0f, %.0f)" % (sum(xs) / len(xs), sum(yv) / len(yv))
            bb = "x[%.0f..%.0f] y[%.0f..%.0f]" % (pct(xs, .05), pct(xs, .95), pct(yv, .05), pct(yv, .95))
        else:
            cen = bb = "-"
        w("  %2d %-11s cells %7d sites %6d  cat[%s]  SLR[%s]  centroid %s  %s" % (
            i, KEYS[i], block_cells[i], len(bs), " ".join(str(cats[c]) for c in range(8)),
            " ".join("%s:%d" % (s[-1], slrs[s]) for s in slr_names), cen, bb))
    w("")
    w("== Geometry ==")
    w("  extent x %s y %s (all device sites of categories CLB..GT)" % (ext_x, ext_y))
    for s in slr_ranges:
        w("  %s CLB RPM_Y %s" % (s["name"], s["y"]))
    w("  pitch %s" % json.dumps(pitch))
    w("  columns entries: %s" % {k: len(v) for k, v in columns.items()})
    w("")
    w("== IO / GT columns touched by DDR4 and XDMA (any site holding >=1 of the block's cells) ==")
    for i in (1, 2, 3, 4, 14):
        for ci in (4, 5):
            mem = [sites[l] for l in block_members[i] if sites[l][4] == ci]
            xs = sorted({m[1] for m in mem})
            yr = (min(m[2] for m in mem), max(m[2] for m in mem)) if mem else None
            crs = sorted({m[3] for m in mem})
            sl = sorted({m[5] for m in mem})
            w("  %-7s %-2s sites %4d RPM_X %s RPM_Y range %s SLR %s clock regions %s" % (
                KEYS[i], TYPES[ci], len(mem), xs, yr, sl, crs))
    w("  device IO columns: %s" % columns["IO"])
    w("  device GT columns: %s" % columns["GT"])
    w("")
    w("== Site-type categorisation (device site counts) ==")
    for (st, c), n in sorted(type_hist.items(), key=lambda t: (t[0][1], t[0][0])):
        w("  %-6s %-24s %7d" % (TYPES[c], st, n))
    w("")
    w("== Used-site types in OTHER / CLK categories ==")
    oc = collections.Counter((TYPES[u[1]], sites[u[5]][0]) for u in used if u[1] >= 6)
    for k, n in sorted(oc.items()):
        w("  %s %s %d" % (k[0], k[1], n))
    w("")
    w("== Shared sites (cells from >1 block): %d ==" % shared)
    for (cat, ks), n in shared_examples.most_common(15):
        w("  %5d  %-5s %s" % (n, cat, "+".join(ks)))
    w("")
    w("== Primitive cells without LOC: %d ==" % len(noloc))
    nr = collections.Counter(r for _, r in noloc)
    for r, n in nr.most_common(15):
        w("  %-20s %d" % (r, n))
    w("")
    w("placement.json: %d bytes, used.count %d" % (os.path.getsize(jp), len(used)))
    with open(os.path.join(D, "pack_report.txt"), "w") as fh:
        fh.write("\n".join(R) + "\n")
    print("\n".join(R))


if __name__ == "__main__":
    main()
