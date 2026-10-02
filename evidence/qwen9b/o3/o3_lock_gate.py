#!/usr/bin/env python3
"""o3_lock_gate.py — the GREEN gate for O3 (plan Task 6 Step 4).

A GATE, NOT A RECORDING.  Every phase has an expected outcome, the script
exits non-zero if any of them misses, and phase 8 is a negative control that
requires the exclusion check to be ABLE to fail (`evidence/qwen9b/g2`'s
standing lesson: a checker that cannot fail proves nothing).

Phases
  1  two processes, one host, one cwd            -> exclusion
  2  two processes, DIFFERENT WORKING DIRS       -> exclusion
     (this checkout, the other git worktree on this machine, and a second
      checkout of the shipped file staged elsewhere — the plan's
      "two-worktree contention test")
  3  two processes, TWO HOSTS over the NFS path  -> exclusion, both ways
  4  a SIGKILLed holder                          -> kernel releases the
     flock; the identity block is stale; --status says so; the next acquire
     rewrites it.  There is no stale lock to break and no --force-unlock.
  5  --exec holds across a sequence; a nested tool INHERITS instead of
     deadlocking; a forged $FABLE5_BOARD_LOCK_HELD does NOT switch it off
  6  --no-lock: takes nothing, shouts on stdout AND stderr, leaves an
     audit line
  7  ADOPTION, measured per tool rather than tabulated: under contention
     every board-touching tool in sw/ REFUSES, and refuses BEFORE it opens
     a device fd or reads an artifact (it is pointed at paths that do not
     exist, so anything other than the lock message means it got there
     first).  The positive half requires the same invocation to get PAST
     the lock when nobody holds it, so an always-refusing tool cannot score
     a perfect red.
  8  NEGATIVE CONTROL: the same challenge against a DIFFERENT lock file
     must NOT be excluded — the pre-O3 per-checkout defect, reproduced
     through the new code, proving phases 1-3 can tell the two apart.

The real board lock is NEVER taken: every phase runs on
`<dir>/.fable5_board.lock.o3test`, in the same directory and on the same
NFS mount as the real one, so the 2B service on `build_035` is untouched.

Usage (snoke or darthplagueis):
  python3 o3_lock_gate.py [--peer HOST] [--skip-peer]
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SW = os.path.join(REPO, "sw")
sys.path.insert(0, SW)
import board_lock as BL                                          # noqa: E402

PY = os.path.join(SW, ".venv", "bin", "python")
if not os.access(PY, os.X_OK):
    PY = sys.executable

# Same directory and mount as the real lock, deliberately NOT the real lock:
# the board is serving the 2B and this gate must not be able to disturb it.
TEST_LOCK = BL.BOARD_LOCK_DEFAULT + ".o3test"

RESULTS = []


def check(name, ok, detail=""):
    """Detail is printed on FAILURE only — a passing log stays readable."""
    RESULTS.append((name, bool(ok), detail))
    print("    [%s] %s%s" % ("ok" if ok else "FAIL", name,
                             ("\n         " + str(detail).replace("\n", " | "))
                             if (detail and not ok) else ""))
    return bool(ok)


def note(text):
    print("      %s" % str(text).replace("\n", " | "))


def hostname():
    import socket
    return socket.gethostname()


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def spawn_holder(path, tool, secs, cwd=None, module=None):
    """Start `board_lock.py --hold`; return (proc, ok) once it really holds."""
    mod = module or os.path.join(SW, "board_lock.py")
    p = subprocess.Popen([PY, mod, "--lock", path, "--tool", tool,
                          "--hold", str(secs)],
                         cwd=cwd or tempfile.gettempdir(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True)
    # Wait for the flock AND for the identity block: the holder writes the
    # block after taking the lock, so "held" alone can still read empty.
    # This gate must not paper over that window -- the LOCK closes it with
    # an fsync and a re-read (sw/board_lock.py), and phase 1 checks the
    # block is really there.
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30.0:
        if BL.probe_state(path)[0] == "held" and BL.read_identity(path):
            return p, True
        if p.poll() is not None:
            return p, False
        time.sleep(0.05)
    return p, False


def challenge(path, tool, cwd=None, module=None):
    """Try to take `path`; return (rc, output)."""
    mod = module or os.path.join(SW, "board_lock.py")
    r = subprocess.run([PY, mod, "--lock", path, "--tool", tool, "--hold", "0"],
                       cwd=cwd or tempfile.gettempdir(),
                       capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def stop(p):
    try:
        p.terminate()
        p.wait(timeout=10)
    except Exception:                                            # noqa: BLE001
        try:
            p.kill()
        except Exception:                                        # noqa: BLE001
            pass


def clean():
    for f in (TEST_LOCK, TEST_LOCK + ".nolock.log"):
        try:
            os.unlink(f)
        except OSError:
            pass


# ----------------------------------------------------------------------
# phases
# ----------------------------------------------------------------------
def phase1():
    print("\n[1] two processes, one host, one working directory")
    h, ok = spawn_holder(TEST_LOCK, "gate_p1_holder", 20)
    check("the holder acquired", ok)
    ident = BL.read_identity(TEST_LOCK)
    note("identity: " + ident)
    d = BL.parse_identity(ident)
    check("the identity block names host, pid, user, tool, time and tree",
          all(k in d for k in ("host", "pid", "user", "tool", "t", "tree")),
          ident)
    check("...and it is THIS host", d.get("host") == hostname(), d.get("host"))
    rc, out = challenge(TEST_LOCK, "gate_p1_challenger")
    check("the second process is REFUSED", rc != 0, "rc=%d" % rc)
    check("the refusal names the holder", "gate_p1_holder" in out, out[:200])
    stop(h)
    t0 = time.monotonic()
    while BL.probe_state(TEST_LOCK)[0] == "held" and time.monotonic() - t0 < 15:
        time.sleep(0.05)
    rc, out = challenge(TEST_LOCK, "gate_p1_after")
    check("the lock is free once the holder exits", rc == 0, "rc=%d" % rc)


def phase2():
    print("\n[2] two processes, DIFFERENT working directories / checkouts")
    # (a) every git worktree of this repo on this machine
    wt = [ln.split(" ", 1)[1].strip()
          for ln in subprocess.run(["git", "worktree", "list", "--porcelain"],
                                   cwd=REPO, capture_output=True,
                                   text=True).stdout.splitlines()
          if ln.startswith("worktree ")]
    check("git reports more than one working tree on this machine",
          len(wt) >= 2, str(wt))
    # (b) a SECOND CHECKOUT of the shipped file: board_lock.py is stdlib-only
    #     and self-contained, so a copy in another tree is that tree's tool.
    tmp = tempfile.mkdtemp(prefix="o3_checkout_b_")
    os.makedirs(os.path.join(tmp, "sw"))
    other = os.path.join(tmp, "sw", "board_lock.py")
    shutil.copy2(os.path.join(SW, "board_lock.py"), other)

    h, ok = spawn_holder(TEST_LOCK, "gate_p2_holder", 25,
                         cwd=wt[0], module=os.path.join(SW, "board_lock.py"))
    check("checkout A holds it", ok)
    for label, cwd, mod in (
            ("the other git worktree (cwd %s)" % (wt[1] if len(wt) > 1 else "-"),
             wt[1] if len(wt) > 1 else wt[0], os.path.join(SW, "board_lock.py")),
            ("a second checkout of the shipped file (%s)" % other, tmp, other)):
        rc, out = challenge(TEST_LOCK, "gate_p2_challenger", cwd=cwd,
                            module=mod)
        check("REFUSED from " + label, rc != 0, "rc=%d %s" % (rc, out[:160]))
        check("...and the refusal names checkout A's holder",
              "gate_p2_holder" in out, out[:200])
    # the path is the SAME regardless of which tree computes it
    r = subprocess.run([PY, "-c",
                        "import sys;sys.path.insert(0,%r);import board_lock;"
                        "print(board_lock.BOARD_LOCK_PATH)"
                        % os.path.dirname(other)],
                       cwd=tmp, capture_output=True, text=True)
    check("the second checkout resolves the SAME lock path",
          r.stdout.strip() == BL.BOARD_LOCK_PATH,
          "%r vs %r" % (r.stdout.strip(), BL.BOARD_LOCK_PATH))
    stop(h)
    shutil.rmtree(tmp, ignore_errors=True)


def phase3(peer, skip):
    print("\n[3] two processes, TWO HOSTS, over the NFS path")
    print("    fstype of the lock's directory: %s"
          % BL._fstype(os.path.dirname(TEST_LOCK)))
    check("the lock lives on a network filesystem (it has to, to cross hosts)",
          BL._fstype(os.path.dirname(TEST_LOCK)).startswith(("nfs", "cifs")),
          BL._fstype(os.path.dirname(TEST_LOCK)))
    if skip or not peer:
        print("    PEER PHASE SKIPPED (--skip-peer or no peer named)")
        RESULTS.append(("cross-host exclusion (peer=%s)" % peer, None,
                        "SKIPPED"))
        return
    rem = ("cd %s && %s sw/board_lock.py --lock %s --tool %%s %%s"
           % (REPO, PY, TEST_LOCK))
    ping = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o",
                           "ConnectTimeout=10", peer, "hostname"],
                          capture_output=True, text=True)
    if ping.returncode != 0:
        print("    PEER UNREACHABLE from %s: %s"
              % (hostname(), (ping.stderr or "").strip()[:120]))
        RESULTS.append(("cross-host exclusion (peer=%s)" % peer, None,
                        "SKIPPED — ssh %s: %s"
                        % (peer, (ping.stderr or "").strip()[:80])))
        return
    check("the peer answers and is a different host",
          ping.stdout.strip() and ping.stdout.strip() != hostname(),
          ping.stdout.strip())

    # 3a: local holds -> the PEER is refused
    h, ok = spawn_holder(TEST_LOCK, "gate_p3_local", 40)
    check("local holder acquired", ok)
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", peer,
                        rem % ("gate_p3_peer", "--hold 0")],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    check("3a: %s is REFUSED while %s holds it" % (peer, hostname()),
          r.returncode != 0, "rc=%d %s" % (r.returncode, out[:160]))
    check("3a: the peer's refusal names the LOCAL holder's host and tool",
          "gate_p3_local" in out and hostname() in out, out[:240])
    stop(h)
    t0 = time.monotonic()
    while BL.probe_state(TEST_LOCK)[0] == "held" and time.monotonic() - t0 < 15:
        time.sleep(0.05)

    # 3b: the PEER holds -> local is refused
    rp = subprocess.Popen(["ssh", "-o", "BatchMode=yes", peer,
                           rem % ("gate_p3_peerhold", "--hold 25")],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True)
    t0 = time.monotonic()
    got = False
    while time.monotonic() - t0 < 40:
        if BL.probe_state(TEST_LOCK)[0] == "held":
            got = True
            break
        time.sleep(0.1)
    check("3b: the peer's hold is visible from %s" % hostname(), got)
    ident = BL.read_identity(TEST_LOCK)
    note("identity written by %s: %s" % (peer, ident))
    check("3b: the identity block names the PEER host",
          BL.parse_identity(ident).get("host") == peer, ident)
    rc, out = challenge(TEST_LOCK, "gate_p3_localchallenge")
    check("3b: %s is REFUSED while %s holds it" % (hostname(), peer),
          rc != 0, "rc=%d" % rc)
    check("3b: the local refusal names the PEER", peer in out, out[:240])
    stop(rp)


def phase4():
    print("\n[4] a SIGKILLed holder: no stale lock, only stale TEXT")
    clean()
    h, ok = spawn_holder(TEST_LOCK, "gate_p4_victim", 60)
    check("the victim acquired", ok)
    ident_before = BL.read_identity(TEST_LOCK)
    # not vacuous: there must BE a block before we can claim it survived
    check("the victim wrote a non-empty identity block",
          bool(ident_before.strip()), repr(ident_before))
    os.kill(h.pid, signal.SIGKILL)
    h.wait()
    t0 = time.monotonic()
    while BL.probe_state(TEST_LOCK)[0] == "held" and time.monotonic() - t0 < 15:
        time.sleep(0.05)
    held, ident, msg = BL.status(TEST_LOCK)
    note("status after SIGKILL: " + msg)
    note("block left behind:    " + ident)
    check("the kernel released the flock when the holder died", not held, msg)
    check("the identity TEXT survived the kill (that is the stale part)",
          ident.strip() == ident_before.strip(), ident)
    check("--status calls it stale rather than held", "STALE" in msg, msg)
    check("--status names the dead holder's pid",
          BL.parse_identity(ident).get("pid") == str(h.pid), ident)
    rc, out = challenge(TEST_LOCK, "gate_p4_next")
    check("the next acquire succeeds — nothing to break, no --force-unlock",
          rc == 0, "rc=%d %s" % (rc, out[:160]))
    check("board_lock.py offers no --force-unlock at all",
          "--force-unlock" not in
          subprocess.run([PY, os.path.join(SW, "board_lock.py"), "--help"],
                         capture_output=True, text=True).stdout)
    check("a fresh acquire OVERWRITES the stale block",
          BL.parse_identity(BL.read_identity(TEST_LOCK)).get("pid")
          != str(h.pid), BL.read_identity(TEST_LOCK))


def phase5():
    print("\n[5] --exec across a sequence, and nesting that must not deadlock")
    clean()
    blk = os.path.join(SW, "board_lock.py")
    inner = ("%s %s --lock %s --check-inherited && echo INHERITED_YES || "
             "echo INHERITED_NO; %s %s --lock %s --tool nested --hold 0 "
             "> /dev/null 2>&1 && echo NESTED_OK || echo NESTED_REFUSED; "
             "cat %s" % (PY, blk, TEST_LOCK, PY, blk, TEST_LOCK, TEST_LOCK))
    r = subprocess.run([PY, blk, "--lock", TEST_LOCK, "--tool", "gate_p5_outer",
                        "--exec", "--", "bash", "-c", inner],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    check("--exec ran the command and returned its rc", r.returncode == 0,
          "rc=%d %s" % (r.returncode, out[:200]))
    check("a nested tool sees a VERIFIED inherited hold",
          "INHERITED_YES" in out, out[:300])
    check("...so it does not deadlock against its own ancestor",
          "NESTED_OK" in out, out[:300])
    check("...and it did NOT overwrite the ancestor's identity block",
          "tool=gate_p5_outer" in out, out[:400])
    check("--exec released the lock afterwards",
          BL.probe_state(TEST_LOCK)[0] != "held")

    # ---- the forgery tests.  THE SECOND ONE IS THE REAL ATTACK. --------
    h, ok = spawn_holder(TEST_LOCK, "gate_p5_realholder", 25)
    check("a real holder is in place for the forgery tests", ok)

    # (1) a marker naming a NON-holder pid (this process).  The weak case:
    #     the first implementation already refused this one.
    env = dict(os.environ)
    env["FABLE5_BOARD_LOCK_HELD"] = "%s:%d:%s" % (hostname(), os.getpid(),
                                                  TEST_LOCK)
    env.pop("FABLE5_BOARD_LOCK_FD", None)
    r = subprocess.run([PY, blk, "--lock", TEST_LOCK, "--tool", "gate_p5_forger",
                        "--hold", "0"], env=env, capture_output=True,
                       text=True, timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    check("a marker naming a NON-holder pid does not get past the lock",
          r.returncode != 0, "rc=%d %s" % (r.returncode, out[:200]))
    check("...and the forger is told who really holds it",
          "gate_p5_realholder" in out, out[:200])

    # (2) THE BYPASS THIS TEST EXISTS FOR.  A marker naming the REAL LIVE
    #     HOLDER passed every check the first implementation made -- same
    #     host, live pid, identity block agrees, lock genuinely held -- and
    #     every one of those is READABLE BY ANYONE, because the identity
    #     block is a world-readable file.  So the env var was a silent
    #     --no-lock for any process on the machine.  Demonstrated at rc=0
    #     INHERITED before the fix; the ancestry proof is now the inherited
    #     FILE DESCRIPTOR, which cannot be named from outside the process
    #     tree.  Phase 5's old forgery test could not see this, because it
    #     used a non-holder pid.
    holder_pid = BL.parse_identity(BL.read_identity(TEST_LOCK)).get("pid")
    check("the real holder's pid is readable from its identity block "
          "(which is exactly why the block cannot be the proof)",
          bool(holder_pid), BL.read_identity(TEST_LOCK))
    env2 = dict(os.environ)
    env2["FABLE5_BOARD_LOCK_HELD"] = "%s:%s:%s" % (hostname(), holder_pid,
                                                   TEST_LOCK)
    env2.pop("FABLE5_BOARD_LOCK_FD", None)
    r = subprocess.run([PY, blk, "--lock", TEST_LOCK, "--tool", "gate_p5_bypass",
                        "--hold", "0"], env=env2, capture_output=True,
                       text=True, timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    check("RED: a marker naming the REAL LIVE HOLDER is REFUSED",
          r.returncode != 0 and "INHERITED" not in out,
          "rc=%d %s" % (r.returncode, out[:300]))
    check("...it is refused as CONTENTION, naming the holder",
          REFUSAL in out and "gate_p5_realholder" in out, out[:300])
    r = subprocess.run([PY, blk, "--lock", TEST_LOCK, "--check-inherited"],
                       env=env2, capture_output=True, text=True, timeout=60)
    check("...and --check-inherited refuses it too",
          r.returncode != 0, "rc=%d" % r.returncode)
    stop(h)


def phase6():
    print("\n[6] --no-lock: the escape, and its audit trail")
    clean()
    h, ok = spawn_holder(TEST_LOCK, "gate_p6_holder", 25)
    check("a holder is in place", ok)
    r = subprocess.run(
        [PY, os.path.join(SW, "seq_run.py"), "--selftest"],
        capture_output=True, text=True, timeout=300)
    check("a board-FREE selftest takes no lock and is unaffected by a holder",
          r.returncode == 0, "rc=%d" % r.returncode)
    r = subprocess.run(
        [PY, os.path.join(SW, "tok_meter.py"), "--lock", TEST_LOCK,
         "--no-lock", "--dev", "/nonexistent/xdma0", "--script",
         "/nonexistent.txt"],
        capture_output=True, text=True, timeout=180)
    check("--no-lock got PAST the lock a holder was holding",
          "REFUSED: another process holds" not in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-200:])
    check("--no-lock shouted on STDOUT", "--no-lock: THE BOARD LOCK IS NOT HELD"
          in r.stdout, r.stdout[:200])
    check("--no-lock shouted on STDERR", "--no-lock: THE BOARD LOCK IS NOT HELD"
          in r.stderr, r.stderr[:200])
    check("--no-lock said someone ELSE was holding it right then",
          "SOMEBODY ELSE IS HOLDING THE BOARD" in r.stdout, r.stdout[:400])
    # THE SHELL TOOLS.  program_fpga.sh / stage1_hw_bringup.sh / test_ctl.sh
    # cannot be run here with the lock FREE -- they would sudo, remove the
    # endpoint and drive vivado.  What is checked instead is that their
    # --no-lock is not a hand-rolled half of the banner: they route it
    # through `board_lock.py --announce-no-lock`, which IS the NullLock the
    # Python tools use, and that path is exercised directly below.
    for name in ("program_fpga.sh", "stage1_hw_bringup.sh", "test_ctl.sh"):
        src = open(os.path.join(SW, name)).read()
        check("%-22s routes --no-lock through board_lock.py" % name,
              "--announce-no-lock" in src)
        check("%-22s uses --check-inherited, not a bash-side marker" % name,
              "--check-inherited" in src)
        check("%-22s does not hand-roll a NO BOARD LOCK banner" % name,
              "NO BOARD LOCK" not in src, name)
    # THE ESCAPE MUST BE COMPLETE.  A script whose --no-lock does not reach
    # its CHILDREN is not an escape: program_fpga.sh and ddr_test.py find no
    # inherited fd, take the lock themselves, and a live holder makes one of
    # them REFUSE in the middle of the sequence -- after the endpoint is out.
    for name in ("stage1_hw_bringup.sh", "test_ctl.sh"):
        src = open(os.path.join(SW, name)).read()
        check("%-22s passes its escape DOWN to the tools it calls" % name,
              "NL=(--no-lock)" in src and '"${NL[@]}"' in src)
    r = subprocess.run([PY, os.path.join(SW, "board_lock.py"), "--lock",
                        TEST_LOCK, "--tool", "shelltool.sh",
                        "--announce-no-lock"],
                       capture_output=True, text=True, timeout=60)
    check("--announce-no-lock shouts on STDOUT",
          "--no-lock: THE BOARD LOCK IS NOT HELD" in r.stdout, r.stdout[:200])
    check("--announce-no-lock shouts on STDERR",
          "--no-lock: THE BOARD LOCK IS NOT HELD" in r.stderr, r.stderr[:200])
    check("--announce-no-lock prints the standing rule",
          "NEVER for a script" in r.stdout, r.stdout[:300])
    check("--announce-no-lock names the holder it is overriding",
          "gate_p6_holder" in r.stdout, r.stdout[:400])

    audit = TEST_LOCK + ".nolock.log"
    txt = open(audit).read() if os.path.exists(audit) else ""
    check("--no-lock left an audit line naming the tool and the argv",
          "tool=tok_meter.py" in txt and "OTHER_HOLDER_PRESENT" in txt, txt[:300])
    check("...and the SHELL tools' escape lands in the same audit file",
          "tool=shelltool.sh" in txt, txt[:400])
    check("...and the lock was NOT taken", BL.parse_identity(
        BL.read_identity(TEST_LOCK)).get("tool") == "gate_p6_holder")
    stop(h)


# every sw/ tool that programs or DMAs the board, with an argv that reaches
# the lock and paths that do not exist, so anything but the lock message
# means the tool got to the device or the artifacts first
TOOLS = [
    ("chat_seq.py",     ["--dev", "/nonexistent/xdma0", "--ntok", "1",
                         "--prompt", "hi"]),
    ("serve.py",        ["--dev", "/nonexistent/xdma0", "--port", "8199"]),
    ("cycle_census.py", ["--dev", "/nonexistent/xdma0"]),
    ("seq_run.py",      ["--prefix", "/nonexistent/x", "--dry-run",
                         "--dev", "/nonexistent/xdma0"]),
    ("infer.py",        ["--dev", "/nonexistent/xdma0", "--ntok", "1",
                         "--prompt", "hi"]),
    ("tok_meter.py",    ["--dev", "/nonexistent/xdma0",
                         "--script", "/nonexistent.txt"]),
    ("mover_bench.py",  ["--dev", "/nonexistent/xdma0", "-n", "1",
                         "--nmv", "1"]),
    ("layer_test.py",   ["--dev", "/nonexistent/xdma0",
                         "--scripts", "/nonexistent.txt"]),
    ("matvec_test.py",  ["--dev", "/nonexistent/xdma0"]),
    ("ddr_test.py",     ["--dev", "/nonexistent/xdma0", "--quick"]),
]
# The shell tools.  RED-ONLY, and deliberately so: with the lock FREE they
# would `sudo pcie_helper.sh remove` and drive vivado, so the GREEN half that
# every Python tool gets cannot be run against them without touching the
# board.  Each refuses BEFORE its first sudo, which is what is checked.
SHELL_TOOLS = [
    ("program_fpga.sh",      ["/nonexistent/bitfile.bit"]),
    ("stage1_hw_bringup.sh", ["/nonexistent/bitfile.bit", "DEADBEEF"]),
    ("test_ctl.sh",          ["A"]),
]
REFUSAL = "REFUSED: another process holds the board lock"


def phase7():
    print("\n[7] adoption, measured per tool (RED under contention, GREEN "
          "without)")
    clean()
    # BOARD SAFETY, CHECKED AND NOT ASSUMED.  The GREEN half runs each tool
    # with the lock FREE, so each one gets past the lock and goes on to open
    # its device.  Every invocation must therefore point --dev at a path
    # that does not exist -- on snoke that is the difference between this
    # gate and mover_bench.py DMAing over the 2B service's resident stream
    # images.  Two tools had the device HARD-CODED and were given --dev by
    # this task for exactly this reason.
    for name, argv in TOOLS:
        check("%-16s is pointed away from the board" % name,
              "--dev" in argv
              and argv[argv.index("--dev") + 1].startswith("/nonexistent"),
              str(argv))
    for name, argv in TOOLS:
        src = open(os.path.join(SW, name)).read()
        check("%-16s imports sw/board_lock" % name,
              "import board_lock as BL" in src)
    h, ok = spawn_holder(TEST_LOCK, "gate_p7_holder", 900)
    check("a holder is in place for the RED half", ok)
    for name, argv in TOOLS:
        cmd = [PY, os.path.join(SW, name), "--lock", TEST_LOCK] + argv
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            out = (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            out, r = "TIMEOUT", None
        check("%-16s RED: refuses under contention" % name,
              r is not None and r.returncode != 0 and REFUSAL in out,
              out[-240:])
        check("%-16s ...before touching a device or an artifact" % name,
              "xdma" not in out.replace("/nonexistent/xdma0", ""),
              out[-240:])
    for name, argv in SHELL_TOOLS:
        cmd = ["bash", os.path.join(SW, name)] + argv
        env = dict(os.environ, FABLE5_BOARD_LOCK=TEST_LOCK)
        env.pop("FABLE5_BOARD_LOCK_FD", None)
        env.pop("FABLE5_BOARD_LOCK_HELD", None)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=120, env=env)
            out = (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            out, r = "TIMEOUT", None
        check("%-22s RED: refuses under contention" % name,
              r is not None and r.returncode != 0 and REFUSAL in out,
              out[-240:])
        check("%-22s ...before its first sudo/pcie_helper" % name,
              "pcie_helper" not in out and "sudo" not in out, out[-240:])
    # F1: THE ENDPOINT MUST COME BACK ON EVERY EXIT PATH.  The original
    # code rescanned inline after the vivado call, so a `set -e` abort, a
    # SIGINT, or a `--jtag-only` failure in a caller with no trap left the
    # device OFF THE PCI TREE with the lock released on unwind -- it then
    # looks dead to lspci and to every tool.  This cannot be EXECUTED here
    # (the real path sudos and drives vivado; T15 owns that -- BOARD_LOCK.md
    # §10.14), so what is pinned is the SHAPE that made it true, on each
    # script that removes the endpoint: an EXIT/INT/TERM trap, a rescan
    # inside it, and the arming flag set BEFORE the remove rather than after
    # (a remove that fails part way still has to be undone, and `set -e`
    # would skip an arming line placed after it).
    for name in ("program_fpga.sh", "stage1_hw_bringup.sh", "test_ctl.sh"):
        src = open(os.path.join(SW, name)).read()
        check("%-22s traps EXIT INT TERM" % name,
              "trap on_exit EXIT INT TERM" in src)
        check("%-22s rescans from inside the trap" % name,
              "$PCIE rescan" in src.split("on_exit()")[-1].split("}")[0],
              src[:0])
        i_arm, i_rm = src.find("NEED_RESCAN=1"), src.find("$PCIE remove")
        check("%-22s arms the rescan BEFORE the remove" % name,
              0 <= i_arm < i_rm, "arm@%d remove@%d" % (i_arm, i_rm))
    stop(h)
    t0 = time.monotonic()
    while BL.probe_state(TEST_LOCK)[0] == "held" and time.monotonic() - t0 < 15:
        time.sleep(0.05)
    print("    -- GREEN half: with nobody holding it, the same invocations "
          "must get PAST the lock (an always-refusing tool cannot pass this)")
    for name, argv in TOOLS:
        cmd = [PY, os.path.join(SW, name), "--lock", TEST_LOCK] + argv
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            out = (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            out = "TIMEOUT"
        check("%-16s GREEN: passes the lock when it is free" % name,
              REFUSAL not in out, out[-240:])


def phase8():
    print("\n[8] NEGATIVE CONTROL — the pre-O3 defect, through the new code")
    clean()
    other = TEST_LOCK + ".other"
    h, ok = spawn_holder(TEST_LOCK, "gate_p8_holder", 20)
    check("a holder is in place on lock A", ok)
    rc, out = challenge(other, "gate_p8_challenger")
    check("a challenger on a DIFFERENT lock file is NOT excluded — which is "
          "exactly the per-checkout bug, and is why phases 1-3 mean something",
          rc == 0, "rc=%d %s" % (rc, out[:160]))
    check("...so the exclusion check can distinguish the two cases",
          rc == 0)
    stop(h)
    for f in (other, other + ".nolock.log"):
        try:
            os.unlink(f)
        except OSError:
            pass


def phase9(trials=12):
    """The identity-block window: who still sees it, and what closes it.

    F7.  A holder takes the flock and THEN writes its block, so a reader
    arriving in that window sees `held` with an EMPTY holder line.  The
    holder-side `fsync` added earlier makes the block DURABLE and visible
    to the other host promptly -- it does NOT make it instantaneous, and
    the window survives it.  What actually closes it for a reader is the
    challenger-side re-read after a short wait, which is why
    `read_identity_settled` exists and why every human-facing reader
    (`--status`, the `--no-lock` banner, the refusal message) goes through
    it.  `read_identity` stays raw for callers that want the byte state.

    This measures both: how often a RAW read lands in the window, and
    whether the SETTLED read ever does.  The raw count may legitimately be
    0 on a quiet machine -- it is reported, not asserted, because a timing
    window cannot be made to reproduce on demand.  The settled side IS
    asserted.
    """
    print("\n[9] the identity-block window (F7): raw vs settled readers")
    clean()
    raw_empty = settled_empty = 0
    for i in range(trials):
        p = subprocess.Popen([PY, os.path.join(SW, "board_lock.py"),
                              "--lock", TEST_LOCK, "--tool",
                              "gate_p9_%d" % i, "--hold", "2"],
                             cwd=tempfile.gettempdir(),
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 20:
            if BL.probe_state(TEST_LOCK)[0] == "held":
                break
            time.sleep(0.0005)
        else:
            stop(p)
            continue
        if not BL.read_identity(TEST_LOCK).strip():
            raw_empty += 1
        if not BL.read_identity_settled(TEST_LOCK).strip():
            settled_empty += 1
        stop(p)
        t0 = time.monotonic()
        while (BL.probe_state(TEST_LOCK)[0] == "held"
               and time.monotonic() - t0 < 10):
            time.sleep(0.01)
    note("%d trials on %s: RAW read empty %d time(s), SETTLED read empty "
         "%d time(s)" % (trials, hostname(), raw_empty, settled_empty))
    check("the SETTLED reader never sees an empty block on a held lock",
          settled_empty == 0, "%d/%d" % (settled_empty, trials))
    if raw_empty == 0:
        note("the raw window did not reproduce in this run -- reported, not "
             "asserted: a timing window cannot be made to appear on demand")
    else:
        note("the raw window DID reproduce, which is the point: the fsync "
             "is not what closes it, the settled re-read is")
    check("every human-facing reader goes through the settled read",
          "read_identity_settled" in open(
              os.path.join(SW, "board_lock.py")).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peer", default=None,
                    help="the other host (default: the other of "
                         "snoke/darthplagueis)")
    ap.add_argument("--skip-peer", action="store_true")
    ap.add_argument("--only", default=None, help="comma-separated phase list")
    a = ap.parse_args()
    peer = a.peer
    if peer is None:
        peer = {"snoke": "darthplagueis",
                "darthplagueis": "snoke"}.get(hostname())

    print("O3 board-lock gate")
    print("  host       %s   peer %s" % (hostname(), peer))
    print("  python     %s" % PY)
    print("  real lock  %s   (NOT touched by this gate)" % BL.BOARD_LOCK_PATH)
    print("  test lock  %s" % TEST_LOCK)
    print("  fstype     %s" % BL._fstype(os.path.dirname(TEST_LOCK)))
    print("  repo       %s" % REPO)

    want = set((a.only or "1,2,3,4,5,6,7,8,9").split(","))
    clean()
    try:
        if "1" in want:
            phase1()
        if "2" in want:
            phase2()
        if "3" in want:
            phase3(peer, a.skip_peer)
        if "4" in want:
            phase4()
        if "5" in want:
            phase5()
        if "6" in want:
            phase6()
        if "7" in want:
            phase7()
        if "8" in want:
            phase8()
        if "9" in want:
            phase9()
    finally:
        clean()

    npass = sum(1 for _, ok, _ in RESULTS if ok is True)
    nfail = sum(1 for _, ok, _ in RESULTS if ok is False)
    nskip = sum(1 for _, ok, _ in RESULTS if ok is None)
    print("\n  %d passed, %d failed, %d skipped" % (npass, nfail, nskip))
    for n, ok, d in RESULTS:
        if ok is False:
            print("  ! %s   %s" % (n, d))
        if ok is None:
            print("  ~ SKIPPED %s   %s" % (n, d))
    print("O3_LOCK_GATE " + ("PASS" if nfail == 0 else "FAIL")
          + (" (with %d skipped)" % nskip if nskip else ""))
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
