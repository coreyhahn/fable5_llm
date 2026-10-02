#!/usr/bin/env python3
"""board_lock.py — THE lock on the one BCU-1525, shared by every checkout.

USER RULING O3 (2026-08-29): *shared flock, mechanized — a single
NFS-visible lock file, holder identity, taken by every tool that programs or
DMAs the board.*

WHAT WAS WRONG, AND IT WAS THE PATH AND NOT THE MECHANISM.
`sw/chat_seq.py`'s `SeqLock` has always been a correct exclusive
`fcntl.flock(LOCK_EX|LOCK_NB)` over a file whose first 256 bytes name the
holder.  Its path was `os.path.join(SW_DIR, ".seq.lock")` — *inside the
checkout that computes it*.  Two checkouts share this machine and one
board, so they locked two different inodes and excluded nothing.  Captured,
not asserted: `evidence/qwen9b/o3/00_red_percheckout.log`.

THE PATH (plan Task 6 Step 2).  One fixed file, above every checkout, on
the tree both hosts mount:

    /home/cah/r2d2/code/fpga/.fable5_board.lock

resolved in this order:
    1. `$FABLE5_BOARD_LOCK`      (an explicit relocation; a `--lock` flag
                                  on an adopting tool is the same override)
    2. `BOARD_LOCK_DEFAULT`      (the literal above)

It is a LITERAL on purpose.  Deriving it from `__file__` would give each
checkout its own answer, which is the defect this file exists to remove.
`/home/cah/r2d2/code` is one NFS export (`<nfs-server>:/tank12t/code`, nfs4)
mounted at the identical path on snoke and on darthplagueis, so the literal
resolves to the same inode on every host that can reach the board.
`.../fpga/` — not `.../fpga/fable5_llm/` — because `fable5_llm` and
`grok46_llm/fable5` are two working trees of one repo and the lock belongs
to neither.

NFS.  `flock()` over NFSv4 is emulated by the client as a whole-file
POSIX lock and works, but the plan says prove it rather than assume it, so
`--probe` records the filesystem type (via `sw/head_cache.py`'s `_fstype`,
whose polarity is the OPPOSITE of this file's: the head cache REFUSES a
network filesystem, this lock REQUIRES one to work across hosts) and the
cross-host demonstration is committed evidence, not an argument.
No new dependency is created by any of this: `sw/.seq.lock` already lived
on the same NFS mount, because the whole repo does.  Only the inode moved.

FAILURE SEMANTICS — the tools must not be brickable by their own lock.
  * contention          -> REFUSE, naming the holder.  That is the point.
  * cannot open/create  -> REFUSE, naming the errno AND both escapes.
                           Fail-closed: a lock that quietly evaporates when
                           the infrastructure hiccups is worse than no lock,
                           because people start trusting it.
  * anything else       -> still `BoardLockError`.  Nothing but this class
                           escapes `acquire()`, so a lock-layer bug can
                           never surface as a traceback mid-session.
  * `release()`         -> NEVER raises.  A shutdown-time lock problem must
                           not mask a run's real result.
  * cost                -> ONE `open` + ONE `flock` + one `fsync` + one
                           `git rev-parse`, once, at process start, BEFORE
                           any device fd.  Nothing on the per-step path.

STALE LOCKS — there are none, and that is a property of `flock`, not a
promise.  The kernel drops the lock when the last fd on it closes, which
includes the process being SIGKILLed, so a dead holder never blocks anyone
and this file deliberately has NO `--force-unlock`.  What CAN go stale is
the 256-byte identity TEXT, which a killed holder does not get to truncate.
`--status` tells the two apart by probing the flock itself, and a
successful `acquire()` rewrites the block, so stale text never survives one
acquisition.  See `evidence/qwen9b/o3/BOARD_LOCK.md` §5.

NESTING.  `--exec` holds the lock across a whole SEQUENCE (that is how
`sw/program_fpga.sh` covers remove -> JTAG -> rescan, the window in which
the device disappears from under everybody).  A tool run inside such a
wrapper would otherwise deadlock against its own ancestor, so `--exec`
leaves the LOCKED fd open across the exec and exports its number in
`FABLE5_BOARD_LOCK_FD`; `acquire()` treats an INHERITED FILE DESCRIPTOR as
the only proof of ancestry.

  **The first cut trusted `FABLE5_BOARD_LOCK_HELD=<host>:<pid>:<path>`
  instead, checking host, a live pid, the identity block and that the lock
  was held.  Every one of those is READABLE by anyone — the identity block
  is a world-readable file — so naming the REAL LIVE HOLDER passed all four
  and the variable was a silent `--no-lock` for any process on the machine.
  Demonstrated, then fixed; the bypass is kept as a RED test in
  `evidence/qwen9b/o3/o3_lock_gate.py` phase 5.**  The string survives for
  MESSAGES only and is never authority; see `_inherited_ok`.

Usage:
  board_lock.py --status                 who holds it, and is it really held
  board_lock.py --probe                  filesystem type + acquire/release
  board_lock.py --hold 10 [--tool NAME]  hold it (tests, manual pauses)
  board_lock.py --exec -- CMD [ARGS...]  run CMD with the lock held
  board_lock.py --check-inherited        exit 0 iff an ancestor holds it
  board_lock.py --announce-no-lock       the full --no-lock banner + audit
  board_lock.py --selftest               single-process unit checks
"""
import argparse
import errno
import fcntl
import os
import subprocess
import sys
import time

SW_DIR = os.path.dirname(os.path.abspath(__file__))

# The one fixed shared path.  See the module docstring for why it is a
# literal, why it sits above every checkout, and why it is on this mount.
BOARD_LOCK_DEFAULT = "/home/cah/r2d2/code/fpga/.fable5_board.lock"
BOARD_LOCK_ENV = "FABLE5_BOARD_LOCK"
BOARD_LOCK_PATH = os.environ.get(BOARD_LOCK_ENV) or BOARD_LOCK_DEFAULT

# Set by --exec in the child environment; honoured only after verification.
INHERIT_ENV = "FABLE5_BOARD_LOCK_HELD"      # DESCRIPTIVE only, never authority
# The ancestry PROOF: the number of the still-open, still-locked fd that
# `--exec` handed down.  A file descriptor cannot be forged from outside
# the process tree, which the identity block could (see _inherited_ok).
INHERIT_FD_ENV = "FABLE5_BOARD_LOCK_FD"

# The legacy per-checkout path, kept BY NAME so the migration is greppable
# and so `--status` can point at a stale one.  Nothing takes it any more.
LEGACY_LOCK_PATH = os.path.join(SW_DIR, ".seq.lock")

IDENT_BYTES = 256

# The standing rule for the escape hatch, printed by --no-lock and repeated
# in docs/USAGE.md §5 and evidence/qwen9b/o3/BOARD_LOCK.md §6.
NOLOCK_RULE = (
    "--no-lock is for a HUMAN who has confirmed sole use of the board.\n"
    "It is NEVER for a script, and NEVER for working around a stuck lock:\n"
    "a lock that will not open is a live holder somewhere, and flock has no\n"
    "stale state to clear (the kernel releases it when the holder dies).")


class BoardLockError(RuntimeError):
    """Refused: someone else holds the board, or the lock is unusable."""


# ----------------------------------------------------------------------
# identity
# ----------------------------------------------------------------------
def _user():
    """The real uid's name, NOT $USER/$LOGNAME.

    `getpass.getuser()` consults `$LOGNAME`, `$USER`, `$LNAME`, `$USERNAME`
    BEFORE the password database, and those are just environment variables
    a caller can hold wrong.  Measured, not hypothetical: this campaign's
    own provenance wrapper does `LOGNAME=$1` for its log-name argument
    (`evidence/qwen9b/run.sh`), and `LOGNAME` is already exported, so every
    tool started through the wrapper stamped the identity block with
    `user=o3/06_probe_snoke.log`.  An identity block whose fields can be
    set by the environment is not identity.
    """
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:                                           # noqa: BLE001
        try:
            import getpass
            return getpass.getuser()
        except Exception:                                       # noqa: BLE001
            return str(os.getuid())


def _host():
    try:
        import socket
        return socket.gethostname()
    except Exception:                                           # noqa: BLE001
        return os.environ.get("HOSTNAME") or "?"


def _tree_sha(cwd):
    """Short HEAD of the checkout the holder is running from ('?' if none).

    Best-effort and time-boxed: this is provenance, and provenance must
    never be able to stop a tool from starting.
    """
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=cwd, capture_output=True, text=True, timeout=5)
        return (r.stdout.strip() or "?") if r.returncode == 0 else "?"
    except Exception:                                           # noqa: BLE001
        return "?"


def _default_tool():
    try:
        return os.path.basename(sys.argv[0]) or "python"
    except Exception:                                           # noqa: BLE001
        return "python"


def identity_line(tool, sha=None):
    """The <=256 byte holder block: host, pid, user, tool, time, tree sha."""
    repo = SW_DIR[:-3] if SW_DIR.endswith("/sw") else SW_DIR
    if sha is None:
        sha = _tree_sha(repo)
    line = ("host=%s pid=%d user=%s tool=%s t=%s tree=%s repo=%s"
            % (_host(), os.getpid(), _user(), tool,
               time.strftime("%Y-%m-%dT%H:%M:%S%z"), sha, repo))
    return line[:IDENT_BYTES - 1] + "\n"


def parse_identity(text):
    """The identity block as a dict; unparseable text yields {}."""
    d = {}
    for tok in (text or "").strip().split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d.setdefault(k, v)
    return d


def read_identity(path=None):
    path = path or BOARD_LOCK_PATH
    try:
        with open(path, "rb") as f:
            return f.read(IDENT_BYTES).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def read_identity_settled(path=None, wait=0.3):
    """`read_identity`, but tolerant of the write-after-lock window.

    A holder takes the flock and THEN writes its identity, so a reader that
    arrives in that millisecond sees an empty block.  Measured: the window
    is real on both hosts and the holder-side `fsync` does NOT close it --
    it makes the block durable, not instantaneous.  What closes it is this:
    if the lock IS held and the block is empty, wait and read again through
    a fresh open (which is also what revalidates the NFS attribute cache).

    Every reader that shows a human who has the board uses this.  Plain
    `read_identity` stays for callers that want the raw byte state.
    """
    path = path or BOARD_LOCK_PATH
    ident = read_identity(path)
    if ident or probe_state(path)[0] != "held":
        return ident
    time.sleep(wait)
    return read_identity(path)


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _age_s(ident):
    t = parse_identity(ident).get("t")
    if not t:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return max(0.0, time.time() - time.mktime(
                time.strptime(t, fmt)[:8] + (-1,)))
        except (ValueError, OverflowError):
            continue
    return None


def probe_state(path=None):
    """('free'|'held'|'absent'|'unknown', detail) — the KERNEL's answer.

    Probes with a fresh fd, so it reports what the kernel thinks and not
    what the identity text claims — which is exactly what tells a live
    holder apart from a block a SIGKILLed holder left behind.

    THE FD MUST BE WRITABLE.  Over NFSv4 `flock()` is emulated as a POSIX
    whole-file lock, and a POSIX *write* lock on a read-only fd is refused
    by the client (EBADF).  A first cut of this function opened `O_RDONLY`
    and scored that refusal as "held", so `--status` reported a free lock
    as HELD on both hosts.  Measured, not reasoned: the bug only appeared
    once the probe ran against the real NFS path.
    """
    path = path or BOARD_LOCK_PATH
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return "absent", "no lock file"
        return "unknown", "open: %s" % e
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return "free", ""
    except OSError as e:
        if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES,
                       errno.EINTR):
            return "held", ""
        return "unknown", "flock: %s" % e
    finally:
        os.close(fd)


def is_locked(path=None):
    """True iff some process currently holds the lock (see probe_state)."""
    return probe_state(path)[0] == "held"


def status(path=None):
    """(held, identity_text, note) — the two failure modes told apart."""
    path = path or BOARD_LOCK_PATH
    st, detail = probe_state(path)
    ident = read_identity_settled(path)
    if st == "absent":
        return False, "", "no lock file yet (nobody has ever taken it here)"
    if st == "unknown":
        return False, ident, (
            "UNKNOWN — the lock could not be probed (%s); treat the board as "
            "TAKEN and ask a human.  The usual cause is PERMISSIONS: the "
            "probe needs an O_RDWR fd (a POSIX write lock over NFS is refused "
            "on a read-only one), so a uid that cannot write the lock file "
            "reads UNKNOWN rather than free/held -- and would also fail to "
            "acquire it.  The file is created 0666; check its mode and owner."
            % detail)
    held = (st == "held")
    d = parse_identity(ident)
    age = _age_s(ident)
    if held:
        note = "HELD"
        if d.get("host") == _host() and d.get("pid"):
            note += " by a LIVE local pid" if _alive(d["pid"]) else (
                " — but the block names local pid %s, which is DEAD: the "
                "holder is on another host, or an fd was leaked to a child"
                % d["pid"])
        elif d.get("host"):
            note += " (the block names host %s; check there)" % d["host"]
    else:
        note = "not held"
        if ident:
            note += " — the identity block below is STALE (a killed holder "
            note += "cannot truncate it; the kernel released the flock)"
    if age is not None:
        note += " [block written %.0f s ago]" % age
    return held, ident, note


# ----------------------------------------------------------------------
# the lock
# ----------------------------------------------------------------------
class BoardLock(object):
    """Exclusive flock on THE board lock, held for the process lifetime.

    Take it BEFORE opening any `/dev/xdma0_*` fd and hold it until exit.
    Refusing to start without it is the point: the sequencer's busy bit is
    a TOCTOU check, not a mutex, and DDR has no busy bit at all.

    Subclass and override `ERROR` to raise a caller's own exception type
    (`sw/chat_seq.py:SeqLock` does exactly that, so no existing caller's
    `except ChatSeqError` stops working).

    CONTEXT-MANAGER CONTRACT: `acquire()` is idempotent (re-entry is a
    no-op, because a second `flock` from the same process on a fresh fd
    would refuse itself) and `__exit__` ALWAYS releases.  So a tool may
    acquire early — to refuse before it does a minute of work — and still
    write `with lock:` around the session body.
    """

    ERROR = BoardLockError

    def __init__(self, path=None, tool=None, log=None):
        self.path = os.path.abspath(path or BOARD_LOCK_PATH)
        self.tool = tool or _default_tool()
        self.log = log
        self.fd = None
        self.inherited = False
        self._inherited_fd = None

    # -- inheritance -------------------------------------------------
    def _inherited_ok(self):
        """True iff THIS process holds an INHERITED fd on the locked file.

        THE PROOF IS THE FILE DESCRIPTOR, NOT THE ENVIRONMENT.  The first
        cut of this checked `$FABLE5_BOARD_LOCK_HELD` for host, a live pid,
        a matching identity block and a held lock — and every one of those
        is READABLE by anyone, because the identity block is a world-
        readable file.  So naming the REAL LIVE HOLDER passed all four, and
        `FABLE5_BOARD_LOCK_HELD=<host>:<holder pid>:<path>` was a silent
        `--no-lock` for any process on the machine.  Demonstrated, then
        fixed: `evidence/qwen9b/o3/o3_lock_gate.py` phase 5 keeps it as a
        RED test.

        `--exec` now leaves the LOCKED fd open across the exec (`pass_fds`
        clears FD_CLOEXEC) and exports its number.  Two facts together are
        the ancestry proof, and neither is forgeable from outside the
        process tree:

          (a) `fstat(fd)` names the same (st_dev, st_ino) as the lock path
              — so the fd really is this lock file; and
          (b) somebody holds the lock (a probe from a FRESH fd fails)
              while `flock(fd, LOCK_EX|LOCK_NB)` on the inherited fd
              SUCCEEDS — which can only happen when that fd's open-file
              description is the holder's own.  An impostor who opens the
              file gets a different OFD, and its flock fails against the
              real holder.

        Both halves are needed: (b) alone would pass when the lock is FREE,
        letting a stray fd suppress a real acquisition.

        The `$FABLE5_BOARD_LOCK_HELD` string is kept for MESSAGES only and
        is never authority.
        """
        fd_s = os.environ.get(INHERIT_FD_ENV) or ""
        if not fd_s.isdigit():
            return False
        fd = int(fd_s)
        try:
            st = os.fstat(fd)
            lst = os.stat(self.path)
        except OSError:
            return False
        if (st.st_dev, st.st_ino) != (lst.st_dev, lst.st_ino):
            return False
        if probe_state(self.path)[0] != "held":
            return False                      # nothing to inherit
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False                      # held, but not by THIS fd
        self._inherited_fd = fd
        return True

    # -- acquire / release -------------------------------------------
    def acquire(self):
        # IDEMPOTENT.  `flock` is per open-file-description, so a second
        # `open`+`flock` from the SAME process on the SAME file refuses
        # itself with EWOULDBLOCK — a tool that acquired early and then said
        # `with lock:` would deadlock against nothing.  Re-entry is a no-op.
        if self.fd is not None or self.inherited:
            return self
        if self._inherited_ok():
            self.inherited = True
            if self.log:
                self.log("  board lock INHERITED from %s (%s) — %s"
                         % (os.environ.get(INHERIT_ENV), self.path, self.tool))
            return self
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        except OSError as e:
            raise self.ERROR(self._unusable(e))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            # The holder takes the flock and THEN writes its identity, so a
            # challenger that arrives in that millisecond sees an empty
            # block.  Re-read once through a fresh open (which is also what
            # revalidates the NFS attribute cache) before giving up on
            # naming who has the board — an anonymous refusal is the one
            # thing this message must not be.
            who = ""
            try:
                who = os.read(fd, IDENT_BYTES).decode("utf-8", "replace").strip()
            except OSError:
                pass
            os.close(fd)
            if not who:
                time.sleep(0.3)
                who = read_identity(self.path)
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES,
                           errno.EINTR):
                raise self.ERROR(self._busy(who))
            raise self.ERROR(self._unusable(e))
        except Exception as e:                                  # noqa: BLE001
            os.close(fd)
            raise self.ERROR(self._unusable(e))
        self.fd = fd
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, identity_line(self.tool).encode())
            # fsync, because the READER is on another host.  Without it the
            # block sits in this client's page cache and a peer that probes
            # the lock in the same second sees it HELD BY NOBODY.  Measured:
            # the first snoke run of evidence/qwen9b/o3/o3_lock_gate.py
            # failed exactly here while darthplagueis had passed.
            os.fsync(fd)
        except OSError:
            # The flock is what excludes; the block is who-to-ask.  Losing
            # the block must not lose the lock.
            pass
        if self.log:
            self.log("  board lock HELD: %s (%s)" % (self.path, self.tool))
        return self

    def release(self):
        """Release.  Never raises — a shutdown problem must not mask a run."""
        if self.inherited:
            # the fd belongs to the ANCESTOR; closing or unlocking it here
            # would drop a lock this process never took
            self.inherited = False
            return
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            os.ftruncate(fd, 0)
        except OSError:
            pass
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    def child_env(self, env=None):
        """`os.environ` plus what a nested tool needs to not deadlock.

        `INHERIT_FD_ENV` is the load-bearing one and it is only meaningful
        alongside `pass_fds=self.pass_fds()` on the spawn -- see
        `_inherited_ok` for why the descriptive marker is not enough.
        """
        e = dict(os.environ if env is None else env)
        fd = self.fd if self.fd is not None else self._inherited_fd
        if fd is not None:
            e[INHERIT_ENV] = "%s:%d:%s" % (_host(), os.getpid(), self.path)
            e[INHERIT_FD_ENV] = str(fd)
            e[BOARD_LOCK_ENV] = self.path
        return e

    def pass_fds(self):
        """The fds a child must inherit for `child_env` to mean anything."""
        fd = self.fd if self.fd is not None else self._inherited_fd
        return (fd,) if fd is not None else ()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *a):
        self.release()

    # -- messages ----------------------------------------------------
    def _busy(self, who):
        return (
            "REFUSED: another process holds the board lock %s"
            % self.path
            + (("\n  holder: " + who) if who else "")
            + "\n  One BCU-1525, one holder.  Every fable5_llm tool that "
              "programs or DMAs the board takes this lock (user ruling O3, "
              "2026-08-29), so the holder above is the whole answer — it "
              "names the host, pid, user, tool, time and checkout."
              "\n  Look:  pgrep -af 'chat_seq|serve|seq_run|infer|tok_meter|"
              "mover_bench|layer_test|matvec_test|ddr_test|cycle_census'"
              "\n  Read:  python3 %s/board_lock.py --status"
              "\n  If you are certain you have the board to yourself, every "
              "tool takes --no-lock.  Read what that means first: "
              "evidence/qwen9b/o3/BOARD_LOCK.md §6." % SW_DIR)

    def _unusable(self, e):
        return (
            "REFUSED: the board lock %s is UNUSABLE (%s)"
            % (self.path, e)
            + "\n  This is fail-CLOSED on purpose: a lock that quietly "
              "evaporates when the filesystem hiccups is worse than no lock."
              "\n  The file lives on the same NFS mount as this checkout, so "
              "if it is unreachable the tools are too."
              "\n  Relocate it with $%s=<path> (every participant must agree "
              "on the path, or it excludes nothing), or take the board "
              "explicitly with --no-lock." % BOARD_LOCK_ENV)


class NullLock(object):
    """What `--no-lock` returns: the same shape, no exclusion, LOUD.

    Every use is announced on stdout AND stderr and appended to
    `<lockpath>.nolock.log`, because an escape hatch nobody can audit is
    not a safety valve, it is a hole.
    """

    def __init__(self, path=None, tool=None, log=None, reason=""):
        self.path = os.path.abspath(path or BOARD_LOCK_PATH)
        self.tool = tool or _default_tool()
        self.log = log
        self.reason = reason
        self.inherited = False
        self.fd = None

    def acquire(self):
        # status() uses read_identity_settled, so the banner names the holder
        # even when the escape is taken microseconds after they took the lock
        held, ident, note = status(self.path)
        banner = [
            "*" * 72,
            "*** --no-lock: THE BOARD LOCK IS NOT HELD BY %s (pid %d)"
            % (self.tool, os.getpid()),
            "*** lock  %s" % self.path,
            "*** state %s" % note,
        ]
        if ident:
            banner.append("*** other %s" % ident)
        if held:
            banner.append("*** SOMEBODY ELSE IS HOLDING THE BOARD RIGHT NOW "
                          "AND YOU ARE PROCEEDING ANYWAY.")
        banner += ["*** " + ln for ln in NOLOCK_RULE.splitlines()]
        banner.append("*" * 72)
        text = "\n".join(banner)
        print(text, flush=True)
        print(text, file=sys.stderr, flush=True)
        if self.log:
            self.log("  board lock NOT HELD (--no-lock)")
        try:                                    # audit trail, best-effort
            with open(self.path + ".nolock.log", "a") as f:
                f.write("%s %s ARGV=%s\n"
                        % (identity_line(self.tool).strip(),
                           "OTHER_HOLDER_PRESENT" if held else "no_other_holder",
                           " ".join(sys.argv[:8])))
        except OSError:
            pass
        return self

    def release(self):
        return

    def child_env(self, env=None):
        return dict(os.environ if env is None else env)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *a):
        self.release()


# ----------------------------------------------------------------------
# the argparse contract every adopting tool uses
# ----------------------------------------------------------------------
def add_lock_args(ap, default=None):
    """`--lock PATH` and `--no-lock`, worded the same way in every tool."""
    ap.add_argument("--lock", default=default or BOARD_LOCK_PATH,
                    help="the shared board lock (default %(default)s; "
                         "$" + BOARD_LOCK_ENV + " overrides the default)")
    ap.add_argument("--no-lock", action="store_true",
                    help="run WITHOUT the board lock.  For a human who has "
                         "confirmed sole use of the board; never for a "
                         "script, and never to get past a stuck lock.  Logged "
                         "loudly on stdout, stderr and <lock>.nolock.log")
    return ap


def from_args(args, tool=None, log=None, error=None):
    """The lock an adopting tool should hold, from its parsed args."""
    path = getattr(args, "lock", None) or BOARD_LOCK_PATH
    if getattr(args, "no_lock", False):
        return NullLock(path, tool=tool, log=log)
    lk = BoardLock(path, tool=tool, log=log)
    if error is not None:
        lk.ERROR = error
    return lk


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def _fstype(path):
    """Filesystem type of the mount `path` lives on ('' if unknown).

    Same shape as `sw/head_cache.py:_fstype`, and the opposite polarity:
    that one REFUSES a network filesystem for the 1 GB head cache, this one
    NEEDS one to work so two hosts can exclude each other.  Duplicated
    rather than imported because `head_cache` pulls in numpy and this file
    must stay stdlib-only and cheap.
    """
    try:
        with open("/proc/mounts") as f:
            mounts = [ln.split()[:3] for ln in f]
    except OSError:
        return ""
    p = os.path.abspath(path)
    best, kind = "", ""
    for _dev, mp, ty in mounts:
        mp = mp.replace("\\040", " ")
        if (p == mp or p.startswith(mp.rstrip("/") + "/")) and len(mp) > len(best):
            best, kind = mp, ty
    return kind


def _cmd_status(path):
    held, ident, note = status(path)
    print("board lock  %s" % path)
    print("  fstype    %s" % (_fstype(path) or "?"))
    print("  state     %s" % note)
    print("  identity  %s" % (ident or "(empty)"))
    legacy = LEGACY_LOCK_PATH
    if os.path.exists(legacy):
        li = read_identity(legacy)
        print("  legacy    %s exists (%s) — NOTHING TAKES IT ANY MORE; it is "
              "the per-checkout file O3 replaced"
              % (legacy, probe_state(legacy)[0]))
        if li:
            print("            stale block: %s" % li)
    return 0 if not held else 3


def _cmd_probe(path):
    print("board lock  %s" % path)
    print("  fstype    %s" % (_fstype(path) or "?"))
    print("  host      %s" % _host())
    t0 = time.monotonic()
    lk = BoardLock(path, tool="board_lock.py --probe")
    try:
        lk.acquire()
    except BoardLockError as e:
        print("  PROBE     REFUSED\n%s" % e)
        return 1
    dt = time.monotonic() - t0
    ident = read_identity(path)
    lk.release()
    print("  acquire   OK in %.3f s" % dt)
    print("  identity  %s" % ident)
    print("  release   OK (block truncated: %r)" % read_identity(path))
    print("BOARD_LOCK_PROBE PASS")
    return 0


def _cmd_hold(path, tool, secs):
    lk = BoardLock(path, tool=tool, log=print)
    lk.acquire()
    print("  identity  %s" % read_identity(path))
    sys.stdout.flush()
    time.sleep(secs)
    lk.release()
    print("  released")
    return 0


def _cmd_exec(path, tool, argv):
    if not argv:
        print("--exec needs a command after --", file=sys.stderr)
        return 2
    lk = BoardLock(path, tool=tool, log=print)
    lk.acquire()
    try:
        # pass_fds keeps the LOCKED fd open across the exec (it also clears
        # FD_CLOEXEC), which is the only thing a descendant can use as proof
        # of ancestry -- see BoardLock._inherited_ok.  bash passes inherited
        # non-CLOEXEC fds on to ITS children, so a grandchild tool inherits
        # it too, which is what makes program_fpga.sh's nested calls work.
        return subprocess.call(argv, env=lk.child_env(),
                               pass_fds=lk.pass_fds())
    finally:
        lk.release()
        print("  board lock released (%s)" % tool)


def BL_user_ok(ident):
    """The identity block's `user` is the real uid's name, not $LOGNAME."""
    import pwd
    return parse_identity(ident).get("user") == pwd.getpwuid(os.getuid()).pw_name


def _selftest(path):
    """Single-process checks.  Multi-process/host lives in the O3 gate."""
    import tempfile
    ok = [True]

    def check(name, cond, extra=""):
        print("    [%s] %s%s" % ("ok" if cond else "FAIL", name,
                                 ("  " + extra) if extra and not cond else ""))
        ok[0] = ok[0] and bool(cond)

    print("board_lock selftest (single process, temp path):")
    d = tempfile.mkdtemp(prefix="blk_")
    p = os.path.join(d, "board.lock")

    check("the default path is the fixed shared one, not this checkout's sw/",
          BOARD_LOCK_DEFAULT == "/home/cah/r2d2/code/fpga/.fable5_board.lock"
          and not BOARD_LOCK_DEFAULT.startswith(SW_DIR),
          BOARD_LOCK_DEFAULT)
    check("the legacy per-checkout path is named and IS inside a checkout",
          LEGACY_LOCK_PATH.startswith(SW_DIR))
    check("$%s overrides the default" % BOARD_LOCK_ENV,
          (os.environ.get(BOARD_LOCK_ENV) or BOARD_LOCK_DEFAULT)
          == BOARD_LOCK_PATH)

    a = BoardLock(p, tool="selftest_a")
    a.acquire()
    check("acquire writes the identity block", bool(read_identity(p)))
    # re-entry must be a no-op, not a self-deadlock: a tool that acquires
    # early and then writes `with lock:` does exactly this.
    fd0 = a.fd
    with a as again:
        check("re-acquiring an already-held lock is a no-op",
              again is a and a.fd == fd0)
    check("...and leaving the with-block releases it once", not is_locked(p))
    a.acquire()
    check("...and it is re-acquirable afterwards", is_locked(p))
    d0 = parse_identity(read_identity(p))
    for k in ("host", "pid", "user", "tool", "t", "tree"):
        check("identity carries %s" % k, k in d0, str(d0))
    check("identity pid is this process", d0.get("pid") == str(os.getpid()))
    # the identity must come from the password database, not the environment
    _saved = {k: os.environ.get(k) for k in ("LOGNAME", "USER", "USERNAME")}
    for k in _saved:
        os.environ[k] = "not-a-user"
    a.release()
    a.acquire()
    check("identity user survives a hostile $LOGNAME/$USER",
          BL_user_ok(read_identity(p)), read_identity(p))
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    check("identity block is at most %d bytes" % IDENT_BYTES,
          os.path.getsize(p) <= IDENT_BYTES, str(os.path.getsize(p)))
    check("is_locked() sees it held", is_locked(p))
    check("probe_state() says 'held'", probe_state(p)[0] == "held",
          str(probe_state(p)))
    check("probe_state() says 'absent' for a missing file",
          probe_state(os.path.join(d, "nope.lock"))[0] == "absent")

    b = BoardLock(p, tool="selftest_b")
    try:
        b.acquire()
        check("a second acquire is refused", False)
    except BoardLockError as e:
        check("a second acquire is refused", True)
        check("the refusal names the holder", "selftest_a" in str(e), str(e))
        check("the refusal names --no-lock", "--no-lock" in str(e))

    a.release()
    check("release truncates the identity block", read_identity(p) == "")
    # the NFS trap, as a standing regression: an EXISTING, UNLOCKED file
    # must probe 'free'.  Probing it through a read-only fd returns EBADF on
    # NFSv4 and scores as 'held' — which is what the first cut of
    # probe_state() did, on both hosts, against the real path.
    check("an existing unlocked file probes 'free', not 'held'",
          probe_state(p)[0] == "free", str(probe_state(p)))
    check("is_locked() sees it free after release", not is_locked(p))
    b.acquire()
    check("the lock is reusable after release", is_locked(p))

    # stale identity text: write a block with NO flock behind it
    b.release()
    with open(p, "w") as f:
        f.write("host=%s pid=999999 user=x tool=ghost t=2020-01-01T00:00:00 "
                "tree=deadbee repo=/nowhere\n" % _host())
    held, ident, note = status(p)
    check("a stale block with no flock reports NOT held", not held)
    check("status() calls the stale block stale", "STALE" in note, note)
    c = BoardLock(p, tool="selftest_c")
    c.acquire()
    check("acquire overwrites a stale block",
          parse_identity(read_identity(p)).get("tool") == "selftest_c")
    c.release()

    # inheritance: a forged marker must NOT switch the lock off
    os.environ[INHERIT_ENV] = "%s:%d:%s" % (_host(), os.getpid(), p)
    d_ = BoardLock(p, tool="selftest_d")
    check("a forged inherit marker does not stop a real acquire",
          d_._inherited_ok() is False)
    d_.acquire()
    check("...and the real acquire happened", d_.fd is not None
          and not d_.inherited)
    check("child_env exports the marker", INHERIT_ENV in d_.child_env())
    d_.release()
    os.environ.pop(INHERIT_ENV, None)

    # release() must never raise, even called twice / on a fresh object
    try:
        d_.release()
        BoardLock(p, tool="x").release()
        check("release() never raises", True)
    except Exception as e:                                      # noqa: BLE001
        check("release() never raises", False, repr(e))

    # an unusable path fails CLOSED with a BoardLockError, not a traceback
    try:
        BoardLock(os.path.join(d, "no", "such", "dir", "x.lock")).acquire()
        check("an unusable path is refused", False)
    except BoardLockError as e:
        check("an unusable path is refused", True)
        check("the unusable message names the env override",
              BOARD_LOCK_ENV in str(e))
    except Exception as e:                                      # noqa: BLE001
        check("an unusable path raises BoardLockError and nothing else",
              False, repr(e))

    # subclassed ERROR (what chat_seq.SeqLock does)
    class MyErr(RuntimeError):
        pass

    class MyLock(BoardLock):
        ERROR = MyErr

    e1 = MyLock(p, tool="e1")
    e1.acquire()
    try:
        MyLock(p, tool="e2").acquire()
        check("a subclass raises its own ERROR", False)
    except MyErr:
        check("a subclass raises its own ERROR", True)
    e1.release()

    # NullLock
    n = NullLock(p, tool="selftest_null")
    n.acquire()
    check("NullLock takes nothing", not is_locked(p))
    check("NullLock appends an audit line",
          os.path.exists(p + ".nolock.log")
          and "selftest_null" in open(p + ".nolock.log").read())
    n.release()

    for f in (p, p + ".nolock.log"):
        if os.path.exists(f):
            os.unlink(f)
    os.rmdir(d)
    print("BOARD_LOCK_SELFTEST " + ("PASS" if ok[0] else "FAIL"))
    return 0 if ok[0] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lock", default=BOARD_LOCK_PATH)
    ap.add_argument("--tool", default=None, help="holder name in the block")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check-inherited", dest="check_inherited",
                   action="store_true",
                   help="exit 0 iff an ancestor VERIFIABLY holds this lock "
                        "(shell wrappers use this so they do not re-take it, "
                        "and so a forged $" + INHERIT_ENV + " cannot switch "
                        "the lock off)")
    g.add_argument("--status", action="store_true")
    g.add_argument("--probe", action="store_true")
    g.add_argument("--hold", type=float, metavar="SECS")
    g.add_argument("--exec", dest="exec_", action="store_true")
    g.add_argument("--announce-no-lock", dest="announce_no_lock",
                   action="store_true",
                   help="print the FULL --no-lock banner (stdout AND stderr, "
                        "the current holder, the standing rule) and append "
                        "the audit line, then exit 0.  This is how the SHELL "
                        "tools get identical --no-lock behaviour instead of "
                        "hand-rolling half of it")
    g.add_argument("--selftest", action="store_true")
    # F9: split at the FIRST bare `--` ourselves.  parse_known_args would
    # happily consume a `--lock`, `--tool` or `--status` belonging to the
    # COMMAND being wrapped -- `--exec -- mytool --status` used to run
    # board_lock's own --status and never launch mytool.  Everything after
    # the first `--` is the command and is never parsed as our own option.
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = []
    if "--" in argv:
        i = argv.index("--")
        argv, rest = argv[:i], argv[i + 1:]
    a, extra = ap.parse_known_args(argv)
    if extra and not rest:
        rest = extra                      # `--exec cmd args` without the --
    try:
        return _dispatch(a, rest)
    except BoardLockError as e:
        print("*** %s" % e, file=sys.stderr)
        return 4


def _dispatch(a, rest):
    if a.check_inherited:
        return 0 if BoardLock(a.lock)._inherited_ok() else 1
    if a.announce_no_lock:
        NullLock(a.lock, tool=a.tool or "board_lock.py --no-lock").acquire()
        return 0
    if a.status:
        return _cmd_status(a.lock)
    if a.probe:
        return _cmd_probe(a.lock)
    if a.selftest:
        return _selftest(a.lock)
    if a.hold is not None:
        return _cmd_hold(a.lock, a.tool or "board_lock.py --hold", a.hold)
    return _cmd_exec(a.lock, a.tool or (rest[0] if rest else "board_lock.py"),
                     rest)


if __name__ == "__main__":
    sys.exit(main())
