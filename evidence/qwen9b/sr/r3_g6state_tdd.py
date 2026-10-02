#!/usr/bin/env python3
"""r3_g6state_tdd.py — Task R3-0 (iv): evidence/qwen9b/g6/g6_state.py's VERSION
check before its state-region DMA, tested against a MOCK device.

    /home/cah/.venv/bin/python evidence/qwen9b/sr/r3_g6state_tdd.py

Run by evidence/qwen9b/sr/r3_tool_tdd.sh as its case (f) (on snoke, through
evidence/qwen9b/sr/sr_run.sh).  BOARD-FREE, SR6's pattern
(evidence/qwen9b/sr/sr6_host_tdd.py make_dev): the mock is a subclass of the
REAL sw/seq_run.Dev whose constructor resolves the expectation exactly as the
real one does (SR.resolve_expect_version with the REAL environment) and runs
the REAL identity gate (_gate) over a scripted CSR map; every write and DMA
method is a TRIPWIRE that records its name and raises.  Reaching
dma_write_chan / dma_read_chan is what "proceeds to the (mock) write" means;
never reaching one is "refused before any DMA".  os.open is wrapped so any
path naming xdma raises (no real device node is ever opened), the board lock
is a scratch file (FABLE5_BOARD_LOCK set before board_lock is imported), and
seq_run.Artifacts / verify_state_image are replaced by a 64-byte fake state
region, so no real artifact is read.  Each case runs in its OWN child
process (this file with --one), so a case that trips a DMA mid-lock cannot
leave the scratch lock held for the next case; a refusal counts only when
the child printed g6_state's own "REFUSING the state-region DMA" line (a
board-lock refusal is also exit 4 and must not pass for one).

Cases (the plan's R3-0 Step 1 (f), then two extra refusals):
  f1  board VERSION 0x266E3AE7 (build_045_r2_incr), FABLE5_SEQ_EXPECT_VERSION
      unset -> refused, exit 4, no DMA
  f2  board 0x266E3AE7, variable `266e3ae7` -> proceeds to the (mock) write
  f3  board 0xC973C18A (build_041, the shipped default), unset -> proceeds
  f4  variable naming a VERSION outside SEQ_VERSIONS (`deadbeef`) -> refused,
      exit 4, no DMA
  f5  board 0x266E3AE7, variable `c973c18a` -> refused, exit 4, no DMA
  f6  --readback (a READ DMA) on board 0x266E3AE7, unset -> refused, exit 4,
      dma_read_chan untouched

RED PREDICTION (against c5f255d's g6_state.py, which has no check): f1, f5
and f6 FAIL (each reaches its DMA tripwire), f4 FAILS (the unknown name
raises ValueError out of Dev's own resolve — a traceback, not exit 4);
f2 and f3 PASS.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".."))
T = tempfile.mkdtemp(prefix="r3_g6state_tdd.")
os.environ["FABLE5_BOARD_LOCK"] = os.path.join(T, "board.lock")
os.environ.pop("FABLE5_SEQ_EXPECT_VERSION", None)
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref"),
                os.path.join(ROOT, "evidence", "qwen9b", "g6")]

_real_os_open = os.open


def _guarded_open(path, *a, **k):
    if "xdma" in str(path):
        XDMA_OPENS.append(str(path))
        raise RuntimeError(f"TRIPWIRE: opened {path}")
    return _real_os_open(path, *a, **k)


os.open = _guarded_open

import board_lock as BL                                         # noqa: E402
import hwmap as HW                                              # noqa: E402
import seq_run as SR                                            # noqa: E402
import g6_state as G6                                           # noqa: E402

assert BL.BOARD_LOCK_PATH == os.environ["FABLE5_BOARD_LOCK"], BL.BOARD_LOCK_PATH
assert BL.BOARD_LOCK_PATH != BL.BOARD_LOCK_DEFAULT

EVENTS = []
XDMA_OPENS = []
NP = NF = 0


class _Tripped(Exception):
    pass


def check(case, name, cond, detail=""):
    global NP, NF
    ok = bool(cond)
    NP += ok
    NF += not ok
    print(f"  [{case}] {'PASS' if ok else 'FAIL'} {name}"
          + (f"  ({detail})" if detail else ""))


def make_dev(version):
    regs = {HW.R_MAGIC: HW.MAGIC, HW.R_VERSION: version,
            HW.R_CALIB: HW.CALIB_ALL, HW.L_IDENT: HW.LAYER_IDENT}
    regs.update({HW.mv_base(c) + HW.R_IDENT: HW.MV_IDENT0 + c
                 for c in range(4)})

    def trip(name):
        def f(self, *a, **k):
            EVENTS.append(name)
            raise _Tripped(name)
        return f

    class MockDev(SR.Dev):
        def __init__(self, path="/dev/xdma0", chan=0, allow_seq=True,
                     expect_version=SR.EXPECT_DEFAULT, log=print):
            self.chan, self.log = chan, log
            self.n_rd = self.n_wr = 0
            # as the real Dev.__init__: resolve from the REAL environment
            ev = SR.resolve_expect_version(expect_version)
            EVENTS.append("dev")
            self.ident, self.seq_ok, self.seq_why = self._gate(ev, allow_seq)
            self.ddr_off = chan * HW.CH_STRIDE

        def rd(self, a):
            self.n_rd += 1
            return regs.get(a, HW.SEQ_CSR_UNMAPPED)

        wr = trip("wr")
        dma_write = trip("dma_write")
        dma_read = trip("dma_read")
        dma_verify = trip("dma_verify")
        dma_write_chan = trip("dma_write_chan")
        dma_read_chan = trip("dma_read_chan")
        dma_verify_chan = trip("dma_verify_chan")
    return MockDev


class FakeArt(object):
    """A 64-byte state region on channel 0; the image file is real (64 B)."""

    def __init__(self, prefix, base=None, **k):
        self.base = os.path.join(T, "fake")
        self.state = {"dn": 0, "kv": 16, "cv": 32, "end": 64,
                      "sha256": "0" * 64, "final_sha256": "1" * 64}
        with open(self.base + ".state.bin", "wb") as f:
            f.write(bytes(64))


SR.Artifacts = FakeArt
SR.verify_state_image = lambda art: "0" * 64


def one(version, env_val, args):
    """CHILD: run the REAL g6_state.main once against the mock; print RESULT."""
    if env_val is None:
        os.environ.pop("FABLE5_SEQ_EXPECT_VERSION", None)
    else:
        os.environ["FABLE5_SEQ_EXPECT_VERSION"] = env_val
    SR.Dev = make_dev(version)
    try:
        rc = G6.main(["--prefix", os.path.join(T, "fake")] + list(args))
    except _Tripped as e:
        rc = f"TRIPPED:{e}"
    except SystemExit as e:
        rc = e.code
    except Exception as e:                   # noqa: BLE001
        rc = f"EXC:{type(e).__name__}: {e}"
    sys.stdout.flush()
    print("RESULT " + json.dumps({"rc": rc, "events": EVENTS,
                                  "xdma": XDMA_OPENS}))
    return 0


def run(version, env_val, args=("--write-initial",)):
    """PARENT: one case in a child process; return (rc, events, out)."""
    cmd = [sys.executable, "-u", os.path.abspath(__file__), "--one",
           f"{version:08x}", "-" if env_val is None else env_val] + list(args)
    env = dict(os.environ)
    env.pop("FABLE5_SEQ_EXPECT_VERSION", None)
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    out = p.stdout + p.stderr
    res = {"rc": f"NO RESULT (child rc {p.returncode})", "events": [],
           "xdma": []}
    for ln in out.splitlines():
        if ln.startswith("RESULT "):
            res = json.loads(ln[len("RESULT "):])
    for ln in out.splitlines():
        if not ln.startswith("RESULT "):
            print("      | " + ln)
    XDMA_OPENS.extend(res["xdma"])
    print(f"      board {version:#010x}  FABLE5_SEQ_EXPECT_VERSION="
          f"{env_val!r}  {' '.join(args)}  ->  rc {res['rc']!r}  "
          f"events {res['events']}")
    return res["rc"], res["events"], out


DMA = ("dma_write_chan", "dma_read_chan", "dma_write", "dma_read",
       "dma_verify", "dma_verify_chan", "wr")
REFUSAL = "REFUSING the state-region DMA"


def no_dma(ev):
    return not any(e in DMA for e in ev)


def main():
    print("r3_g6state_tdd: g6_state.py's VERSION check, mock Dev, "
          f"scratch lock {BL.BOARD_LOCK_PATH} (one child process per case)")
    V_R2, V_041 = 0x266E3AE7, SR.EXPECTED_SEQ_VERSION
    assert V_R2 in SR.SEQ_VERSIONS and V_041 == 0xC973C18A
    assert 0xDEADBEEF not in SR.SEQ_VERSIONS

    rc, ev, out = run(V_R2, None)
    check("f1", "board 0x266E3AE7, variable unset: refused with exit 4 by "
          "g6_state's VERSION check", rc == 4 and REFUSAL in out,
          f"rc {rc!r}")
    check("f1", "board 0x266E3AE7, variable unset: DMA tripwire untouched",
          no_dma(ev), f"events {ev}")

    rc, ev, out = run(V_R2, "266e3ae7")
    check("f2", "board 0x266E3AE7, variable 266e3ae7: proceeds to the "
          "(mock) write", rc == "TRIPPED:dma_write_chan", f"rc {rc!r}")

    rc, ev, out = run(V_041, None)
    check("f3", "board 0xC973C18A, variable unset: proceeds to the (mock) "
          "write", rc == "TRIPPED:dma_write_chan", f"rc {rc!r}")

    rc, ev, out = run(V_041, "deadbeef")
    check("f4", "variable naming a VERSION outside SEQ_VERSIONS: refused "
          "with exit 4 by g6_state", rc == 4 and REFUSAL in out,
          f"rc {rc!r}")
    check("f4", "outside SEQ_VERSIONS: DMA tripwire untouched", no_dma(ev),
          f"events {ev}")

    rc, ev, out = run(V_R2, "c973c18a")
    check("f5", "board 0x266E3AE7, variable c973c18a: refused with exit 4 "
          "by g6_state", rc == 4 and REFUSAL in out, f"rc {rc!r}")
    check("f5", "board != named VERSION: DMA tripwire untouched", no_dma(ev),
          f"events {ev}")

    rc, ev, out = run(V_R2, None, args=("--readback",))
    check("f6", "--readback on board 0x266E3AE7, variable unset: refused "
          "with exit 4 by g6_state", rc == 4 and REFUSAL in out,
          f"rc {rc!r}")
    check("f6", "--readback refused: dma_read_chan untouched",
          "dma_read_chan" not in ev, f"events {ev}")

    check("f0", "no xdma device node was ever opened (any case)",
          not XDMA_OPENS, f"{XDMA_OPENS}")
    print(f"r3_g6state_tdd: {NP} passed, {NF} failed")
    return 0 if NF == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--one":
        raise SystemExit(one(int(sys.argv[2], 16),
                             None if sys.argv[3] == "-" else sys.argv[3],
                             sys.argv[4:]))
    raise SystemExit(main())
