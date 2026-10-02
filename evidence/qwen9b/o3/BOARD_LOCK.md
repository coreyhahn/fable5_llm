# O3 — the shared board flock, mechanized

**Gate doc for Task 6 of `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`.**
Host-only, filesystem-only: **no `rtl/`, no `synth/`, and the board was never
touched.** The 2B stayed served from `build_035_fp2a_exc_po` throughout.

> **USER RULING O3 (2026-08-29, interactive):** *shared flock, mechanized — a
> single NFS-visible lock file, holder identity, taken by every tool that
> programs or DMAs the board.*
> Decision trail: `.superpowers/sdd/2026-08-25-qwen-next-derisking/progress.md`
> (**LOCAL-ONLY**, gitignored — a fresh clone will not have it).

**Labels** (spec §0): **M** measured on this board · **D** computed by a
committed script that reproduces a committed number first · **T**
toolchain-measured · **E** extrapolated · **S** this document's arithmetic.
Nothing here is **M** — this gate deliberately never touched the board. Every
number below is **D**, from a committed script with a committed log.

---

## §0 The result in one paragraph

`sw/.seq.lock` was a correct `flock` over the **wrong file**: a path inside
whichever checkout computed it. Two checkouts share this machine and one
BCU-1525, so they locked two different inodes and excluded nothing — captured
live in `00_red_percheckout.log`, where both checkouts hold the board at the
same moment. The lock is now
**`/home/cah/r2d2/code/fpga/.fable5_board.lock`** (`sw/board_lock.py:106`), one
inode above every checkout on the NFS export both hosts mount, carrying a
256-byte holder block naming **host, pid, user, tool, time, tree sha and
checkout**. Ten `sw/` tools take it — seven of them for the first time — and
`sw/program_fpga.sh` holds it across the **whole** `remove` → JTAG → `rescan`
sequence, which is the window the ruling was about. `chat_seq.SeqLock` is the
same class under its old name, so no caller broke. Two defects in this gate's
own code were found by running it — one on the peer host, one under the
provenance wrapper — and both are fixed with standing regressions.

| gate | result | log |
|---|---|---|
| RED: the per-checkout lock excludes nothing across checkouts | **CONFIRMED** | `00_red_percheckout.log` |
| the lock gate, darthplagueis (incl. **cross-host, both directions**) | **PASS 100/100** | `01_gate_darthplagueis.log` |
| the lock gate, snoke — **first run, and it FAILED** | **FAIL 88/92** (the fsync race, §5.2) | `02_gate_snoke.log` |
| the lock gate, snoke, after the fix | **PASS** — 93 passed / 0 failed / **1 skipped** | `03_gate_snoke_fsync.log` |
| NFS probe, both hosts | **PASS**, `nfs4` | `11_probe_darthplagueis_usrfix.log`, `12_probe_snoke_usrfix.log` |
| `board_lock.py --selftest` | **PASS 38/38** | `05_board_lock_selftest.log`, `13_board_lock_selftest_snoke.log` |
| citation drift caused by this task | **82 found, 82 fixed, 82 verified** | `14_cite_drift_check.log`, `15_cite_drift_verify.log` |
| citation-drift negative controls | **CAUGHT** both halves | `16_cite_drift_negcontrol_check.log`, `17_cite_drift_negcontrol_verify.log` |
| the regression floor (boardfree + three byte gates) | **all PASS** | §8 |
| **all of it re-run on the committed tree**, `=== tree: 1a6565a`, no dirty flag | **PASS** | `20_…`–`25_…` |

**Fix round 1** (review of `1a6565a`+`a77a819` — 12 findings, F1–F12; the
per-finding corrections are dated blocks in §4.1, §5.2, §6, §8a, §9 and §10):

| gate | result | log |
|---|---|---|
| the lock gate after the fixes, darthplagueis | **PASS 138 / 0 / 0** | `55_gate_darthplagueis_final2.log` |
| the lock gate after the fixes, snoke | **PASS 130 / 0 / 1** (the one-way ssh) | `56_gate_snoke_final2.log` |
| `board_lock.py --selftest`, both hosts | **PASS 38/38** | `38_…darthplagueis.log`, `39_…snoke.log` |
| the widened citation sweep | **109 cited, 21 unmoved, 88 drifted, 88 verified** | `30_…`, `31_…` (+ controls `32_…`, `33_…`) |
| **the second drift class**: citations into the documents this task edited | **32 cited, 18 unmoved, 14 drifted, 14 verified** | `34_…`, `35_…` (+ controls `36_…`, `37_…`) |
| `spec_cites.py` on this document — **RED, and it was this round's own new prose** | **FAIL 25 → PASS 0** | `42_…` (RED), `52_…` (GREEN) |
| `spec_cites.py` on the spec, the plan, and `--selftest` | **PASS** | `43_…`, `44_…`, `46_…` |
| `spec_cites.py` on the seven other documents this round touches | **no count worse than at `a77a819`**; two better | `45_spec_cites_other_gate_docs.log` |
| the regression floor, snoke | **all PASS** | `47_…`–`51_…`, §8b |
| **all of it re-run on the committed tree**, `=== tree: 77584e9`, no dirty flag | **PASS** — gate 138/0/0 + 130/0/1, floor unmoved | `60_…`–`69_…`, §8c |

---

## §1 The RED, captured rather than described

`evidence/qwen9b/o3/o3_red_percheckout.py` imports **each checkout's own**
`sw/chat_seq.py` — the committed code of that checkout, not a transcription —
and asserts both halves of the plan's claim that *the mechanism is right and
the path is wrong*:

```
[control] two processes, ONE checkout
    A  ok=True   lock=/home/cah/r2d2/code/fpga/fable5_llm/sw/.seq.lock
    B  ok=False  why=another process holds …/sw/.seq.lock (pid 2715959 …)
    => EXCLUDED.  The flock mechanism is correct.

[red] two processes, TWO checkouts
    A  ok=True   lock=/home/cah/r2d2/code/fpga/fable5_llm/sw/.seq.lock
    B  ok=True   lock=/home/cah/r2d2/code/fpga/grok46_llm/fable5/sw/.seq.lock
    => BOTH HELD THE BOARD AT ONCE.  Two inodes, one board.
O3_RED_PERCHECKOUT: CONFIRMED
```

Run on **snoke**, tree `dc8f492`, `00_red_percheckout.log`. `git worktree list`
supplies the checkouts, so the test discovers the situation rather than assuming
it: `/home/cah/r2d2/code/fpga/fable5_llm` and
`/home/cah/r2d2/code/fpga/grok46_llm/fable5`. Both `sw/.seq.lock` files existed
on disk before this gate — dated 2026-08-26 and 2026-08-18.

**This script stays RED forever, and that is deliberate.** O3 does not repair
the legacy path, it replaces it; any checkout that has not picked up this
commit still locks its own inode. The GREEN counterpart is `o3_lock_gate.py`.

---

## §2 The path, and why it is a literal

```
/home/cah/r2d2/code/fpga/.fable5_board.lock
```

resolved as `$FABLE5_BOARD_LOCK`, else the literal (`sw/board_lock.py:106-108`).

| decision | reason |
|---|---|
| **one fixed file** | the thing being protected is one physical board. One board, one inode. |
| **a literal, not derived from `__file__`** | a derivation gives each checkout its own answer, which **is** the defect. Deriving it would reproduce `sw/.seq.lock` with extra steps. |
| **`…/fpga/`, not `…/fpga/fable5_llm/`** | `fable5_llm` and `grok46_llm/fable5` are two working trees of one repo; the lock belongs to neither, so it sits above both. |
| **on `/home/cah/r2d2/code`** | that is `<nfs-server>:/tank12t/code`, `nfs4`, mounted at the **identical path** on snoke and darthplagueis (measured, §3). A host that cannot see it cannot reach the board either. |
| **`$FABLE5_BOARD_LOCK` / `--lock` override** | for a second board, or a test that must not disturb the real lock (this gate's own phases use `…/.fable5_board.lock.o3test`). Stated with its trap: **every participant must agree on the path, or it excludes nothing.** |
| **no new dependency** | `sw/.seq.lock` already lived on this NFS mount, because the whole repo does. Only the inode moved. |

`LEGACY_LOCK_PATH` (`sw/board_lock.py:119`) keeps the old path **by name** so
the move is greppable and so `--status` can point at a stale one and say
nothing takes it any more.

---

## §3 The NFS question, answered rather than assumed

The plan asks for a startup probe recording the filesystem type, reusing
`sw/head_cache.py`'s `_fstype` — noting its polarity is the opposite, since the
head cache *refuses* a network filesystem and this lock *needs* one to work.
`sw/board_lock.py:_fstype` is that helper, **duplicated rather than imported**
because `head_cache` pulls in numpy and this module must stay stdlib-only and
cheap; the docstring says so and names the polarity inversion.

`board_lock.py --probe`, both hosts, tree `dc8f492` **[D]**:

| host | fstype | acquire | identity written |
|---|---|---|---|
| darthplagueis | `nfs4` | 0.004 s | `host=darthplagueis pid=950618 user=cah tool=board_lock.py --probe t=2026-09-01T14:21:56-0600 tree=dc8f492 repo=…/fable5_llm` |
| snoke | `nfs4` | 0.005 s | `host=snoke pid=2723998 user=cah …` |

**Mutual exclusion across two hosts is demonstrated, not inferred**, and in
**both directions** (`01_gate_darthplagueis.log` phase 3):

```
3a: snoke is REFUSED while darthplagueis holds it
3a: the peer's refusal names the LOCAL holder's host and tool
3b: the peer's hold is visible from darthplagueis
    identity written by snoke: host=snoke pid=2718282 … tool=gate_p3_peerhold
3b: darthplagueis is REFUSED while snoke holds it
3b: the local refusal names the PEER
```

So the plan's fallback — *"a lock on snoke's local filesystem plus a rule that
only snoke touches the board"* — is **not needed** and was not taken.

**One asymmetry, recorded because it shapes the evidence.** darthplagueis can
`ssh snoke`; snoke **cannot** `ssh darthplagueis` (`Permission denied
(publickey,password)`). So the cross-host phase runs from darthplagueis and is
reported **SKIPPED with its reason** in the snoke log rather than silently
passing. The gate prints `PASS (with 1 skipped)` and the skip is listed by name.

---

## §4 Adoption — measured per tool, not tabulated

`o3_lock_gate.py` phase 7 (`evidence/qwen9b/o3/o3_lock_gate.py:481`) runs
**every** tool twice: once with a holder in place (must REFUSE) and once with
the lock free (must get PAST it). The second half is what stops an
always-refusing tool from scoring a perfect red.

Each tool is invoked with paths that do not exist, so **anything other than the
lock message proves it reached a device or an artifact first** — that is how
"takes the lock BEFORE any device fd" is checked rather than asserted.

The three **shell** tools are RED-only in phase 7, and deliberately so: with
the lock free they would `sudo -n pcie_helper.sh remove` and drive vivado, so
the GREEN half cannot be run against them without touching the board. What is
checked is that each **refuses before its first `sudo`** — the assertion is on
the output, not on a reading of the source — and phase 6 checks separately
that their `--no-lock` is routed through `board_lock.py --announce-no-lock`
rather than hand-rolled. Phase 7 also pins the F1 shape on all three: an
`EXIT INT TERM` trap, a rescan inside it, and the arming flag set **before**
the remove (§10.14 says what that does and does not prove).

| tool | before O3 | now | where |
|---|---|---|---|
| `sw/chat_seq.py` | took `sw/.seq.lock` | shared lock | `main()`, before `ChatSession` |
| `sw/serve.py` | took `sw/.seq.lock` (not `--mock`) | shared lock | before `BoardBackend` |
| `sw/cycle_census.py` | took `sw/.seq.lock` | shared lock | first statement after arg parse |
| `sw/seq_run.py` | **none** | shared lock, `--dry-run` included | before the artifacts are opened |
| `sw/infer.py` | **none** | shared lock | before the ~10 s tokenizer build |
| `sw/tok_meter.py` | **none** | shared lock | before the device |
| `sw/mover_bench.py` | **none** — and it clobbers the chat stream images | shared lock | before the donor stream is read |
| `sw/layer_test.py` | **none** | shared lock | before the device |
| `sw/matvec_test.py` | **none** | shared lock | before the device |
| `sw/ddr_test.py` | **none** — and it overwrites all 16 GiB of DDR | shared lock | before the device |
| `sw/program_fpga.sh` | **none** | shared lock **across `remove` → JTAG → `rescan`** | §4.1 |
| `sw/stage1_hw_bringup.sh` | **none** | one hold for the entire bring-up | §4.1 |
| `sw/test_ctl.sh` | **none** — bare `remove`/`rescan` **and** raw `pread`/`pwrite` on `/dev/xdma0_*` | one hold across `remove` → JTAG → `rescan` → DMA | §4.1 |

Board-free modes deliberately take **no** lock and are checked to be unaffected
by a holder: `--selftest` (`chat_seq`, `serve`, `seq_run`, `board_lock`),
`--mock`, `--model-only`, `--tok-test`. Phase 6 runs `seq_run.py --selftest`
under a live holder and requires rc 0.

`chat_seq.SeqLock` is now `class SeqLock(BL.BoardLock)` with
`ERROR = ChatSeqError` (`sw/chat_seq.py:390`), so `sw/serve.py`'s
`except CS.ChatSeqError` and `cycle_census`'s `CS.SeqLock(CS.LOCK_PATH)` keep
working with no change in behaviour, and `CS.LOCK_PATH` now **is** the shared
path (`sw/chat_seq.py:269`).

### §4.1 The reprogram sequence — the part the ruling was actually about

The dangerous window is not the JTAG call. It is `pcie_helper.sh remove` → JTAG
→ `pcie_helper.sh rescan`, during which the endpoint is **gone from the PCI
tree**, every other process's `/dev/xdma0_*` fd points at nothing, and an MMIO
to a dead endpoint can kernel-panic snoke (CHARTER safety rails). A lock held
only across the JTAG step leaves both ends of that window open.

So `sw/program_fpga.sh` now **runs the sequence itself**, re-executing under
`board_lock.py --exec` so one hold covers all three steps
(`sw/program_fpga.sh:91`). `--jtag-only` keeps the old single-step behaviour for
a caller that owns remove/rescan *and already holds the lock*.

**Nesting had to be solved for this to be safe, and the first solution was
wrong in a way worth writing down.** `flock` is per open-file description, so
a tool run inside a lock-holding wrapper would refuse itself.

The first cut had `--exec` export `FABLE5_BOARD_LOCK_HELD=<host>:<pid>:<path>`
and `acquire()` honour it after four checks: same host, that pid alive, the
identity block naming it, and the lock genuinely held. **Every one of those
four is readable by anybody, because the identity block is a world-readable
file.** So a marker naming the *real live holder* passed all four, and
`FABLE5_BOARD_LOCK_HELD` was **a silent `--no-lock` for any process on the
machine** — the opposite of what the variable was added to do. Found by review
(F3) and demonstrated at `rc=0 INHERITED` before the fix.

**The proof is now the file descriptor, which cannot be named from outside the
process tree** (`sw/board_lock.py:372`). `--exec` leaves the *locked* fd open
across the exec (`pass_fds` clears `FD_CLOEXEC`) and exports its number;
`acquire()` requires **both** of:

- `fstat(fd)` naming the same `(st_dev, st_ino)` as the lock path — so the fd
  really is this lock file; **and**
- somebody holding the lock (a probe from a **fresh** fd fails) while
  `flock(fd, LOCK_EX|LOCK_NB)` on the **inherited** fd succeeds — which can
  only happen when that fd's open-file description *is* the holder's own. An
  impostor who opens the file gets a different OFD, and its `flock` fails
  against the real holder.

Both halves are load-bearing: the second alone would pass when the lock is
**free**, letting a stray fd suppress a real acquisition. The env string
survives for **messages only** and is never authority. `bash` passes inherited
non-`CLOEXEC` fds to its own children, which is what makes the nested calls
inside `sw/program_fpga.sh` and `sw/stage1_hw_bringup.sh` work. Phase 5 keeps the
demonstrated bypass as a **RED test**, alongside the weaker non-holder-pid
forgery the original test used — which is precisely why the original test
could not see this.

> **CORRECTION 2026-09-01 (review F2): `sw/test_ctl.sh` was missed, and it
> was the same hole.** It is in `sw/`, it is listed in
> `docs/ARCHITECTURE.md:733`, and it does **both** dangerous things: a bare
> `pcie_helper.sh remove` / `rescan` pair around a reprogram, and raw
> `os.pwrite`/`os.pread` on `/dev/xdma0_h2c_0` and `_c2h_0`. It took no lock
> at all. Worse, once `sw/program_fpga.sh` started locking, **that** call took
> and *released* a lock of its own, so the outer remove, the rescan and the
> DMA on either side of it were unprotected while *looking* locked — exactly
> the defect `sw/stage1_hw_bringup.sh` was fixed for. It now takes **one** hold
> for the whole script, calls `program_fpga.sh --jtag-only` so the hold is
> inherited rather than re-taken, and has the same rescan-on-exit trap.

**Deviation from the plan's file list, declared:** `sw/stage1_hw_bringup.sh` and
`sw/test_ctl.sh` are not in Task 6's `Files`. Both drive their own remove →
program → rescan, and `stage1` then runs `sw/ddr_test.py` twice over 16 GiB.
Left alone they would have kept an unlocked reprogram window and taken the lock
several separate times with gaps between them, which is the hole this task
exists to close. Each now takes the lock **once** and its children inherit.
Named individually in the commit; nothing else outside the plan's list was
touched.

---

## §5 What running it found — two defects in this gate's own code

Both were found by **running** on a second host and under the provenance
wrapper, not by reading, and both now have a standing regression.

### §5.1 `probe_state` was wrong on NFS in the "free" direction

The first `is_locked()` opened the lock `O_RDONLY` and asked for `LOCK_EX`.
Over NFSv4 `flock` is emulated as a POSIX whole-file lock, and a POSIX **write**
lock on a read-only fd is refused by the client — which the code scored as
*held*. `--status` therefore reported a **free** lock as `HELD` on **both**
hosts, and said the same about the legacy file. Fixed by probing through an
`O_RDWR` fd and classifying the errno
(`sw/board_lock.py:263`); the selftest now pins that *an existing, unlocked
file probes `free`*. **It only appeared against the real NFS path** — a
`/tmp` unit test would have passed.

### §5.2 The identity block races the lock — and the window is still there

The holder takes the `flock` and *then* writes its identity, so a reader that
arrives in between sees the lock **held by nobody**. On snoke — 48 cores,
different timing — the first full gate run **FAILED 4 checks**
(`02_gate_snoke.log`). **This is the value of the plan's insistence on two
hosts:** darthplagueis had already passed 100/100 with the same racy code.

> **CORRECTION 2026-09-01 (review F7). An earlier revision of this section
> credited the fix to the holder-side `fsync`. That is wrong, and the
> reviewer measured it: the window survives the committed code.** This
> gate now measures it too — phase 9, `12 trials, RAW read empty 12/12,
> SETTLED read empty 0/12` on darthplagueis. The `fsync`
> (`sw/board_lock.py:478`) makes the block **durable and promptly visible to
> the other host**, which is worth having; it does not make it
> **instantaneous**, and nothing can. **What closes the window for a reader
> is the challenger-side re-read**: `read_identity_settled` waits and reads
> again through a fresh open when the lock is held but the block is empty.

**Which readers are covered, stated because the answer is "not all of them by
default".** Everything that shows a human who has the board now goes through
`read_identity_settled`: the refusal message, `--status`, and the `--no-lock`
banner. Plain `read_identity` stays raw for callers that want the byte state —
and a caller using it directly **can** momentarily see `HELD` with an empty
identity. Phase 9 asserts the settled side and *reports* the raw side rather
than asserting it, because a timing window cannot be made to reproduce on
demand: on a quiet machine the honest answer is "it did not appear this run".

The gate also waits for the block as well as the flock before challenging, and
phase 4 was made non-vacuous — it had compared two empty strings and called
that "the text survived".

### §5.3 A third, found by the provenance wrapper: `user=` was forgeable

`evidence/qwen9b/run.sh` does `LOGNAME=$1` for its log-name argument, and
`LOGNAME` is already exported, so `getpass.getuser()` — which consults
`$LOGNAME`/`$USER` **before** the password database — stamped the block
`user=o3/06_probe_snoke.log`. An identity field an environment variable can set
is not identity. `_user()` now reads `pwd.getpwuid(os.getuid())`
(`sw/board_lock.py:139`) and the selftest sets `$LOGNAME`/`$USER`/`$USERNAME`
to `not-a-user` and requires the block to be right anyway. Logs `04`/`06` are
kept showing the defect; `11`/`12` are the corrected probes.

---

## §6 `--no-lock` — the escape hatch, written out by name

**The plan carries `--no-lock` as an affordance the ruling did not authorize.
It is kept, and this section is the audit trail the plan asked for**: *"an
escape hatch that lives only in `--help` is an escape hatch nobody audits."*

**Which tools accept it, by name:**

| tool | how to ask for it |
|---|---|
| the ten Python tools in §4's table | `--no-lock` |
| `sw/program_fpga.sh` | `--no-lock` |
| `sw/test_ctl.sh` | `--no-lock` |
| `sw/stage1_hw_bringup.sh` | **`STAGE1_NO_LOCK=1`** in the environment |

The Python flag comes from one shared helper (`BL.add_lock_args`), so its
wording and behaviour cannot drift apart between tools.

> **`STAGE1_NO_LOCK=1` (review F4).** It was originally an undocumented,
> unaudited env escape on **the most dangerous script in `sw/`** — the one
> that removes the endpoint, reprograms it and then writes all 16 GiB of
> DDR twice. It is kept, because a bring-up on a board nobody else can
> reach is a real case, but it is no longer quiet: it goes through
> `board_lock.py --announce-no-lock`, so it prints the same banner on both
> streams, names the current holder and lands in the same audit file as
> every other escape. It is an environment variable rather than a flag only
> because the script's positional arguments are fixed by its callers.

> **The shell tools used to hand-roll half of it (review F5).** §6's "every
> time" list below was false for `sw/program_fpga.sh`: it printed three lines
> on stdout only — no stderr copy, no standing rule, no audit line. All
> three shell tools now call `board_lock.py --announce-no-lock`, which *is*
> the `NullLock` the Python tools use, so the behaviour cannot drift by
> construction. Gate phase 6 checks both the routing (no tool contains a
> hand-rolled banner) and the shared implementation's output.

> **An escape that does not reach the children is not an escape.** Found
> while writing F4/F5 up: `sw/stage1_hw_bringup.sh` and `sw/test_ctl.sh`
> call tools that take the lock themselves — `program_fpga.sh --jtag-only`,
> and `sw/ddr_test.py` twice — and with the escape taken there is no hold to
> inherit, so each of them would have taken the lock on its own and a live
> holder would have made one **REFUSE in the middle of the sequence, after
> the endpoint was already off the bus.** Both scripts now pass `--no-lock`
> down (`NL=(--no-lock)`), and phase 6 checks that they do.

**What it logs**, every time (`sw/board_lock.py:566`):

1. a banner on **stdout**;
2. the identical banner on **stderr**;
3. the current holder, if any — and if somebody *is* holding the board, the
   extra line `*** SOMEBODY ELSE IS HOLDING THE BOARD RIGHT NOW AND YOU ARE
   PROCEEDING ANYWAY.`;
4. an append to **`<lock>.nolock.log`** carrying the full identity line
   (host, pid, user, tool, time, tree, checkout), whether another holder was
   present, and the first eight argv words. Best-effort and wrapped: a failure
   to write the audit line must not stop the tool.

**THE STANDING RULE, and it is the whole reason this section exists:**

> **`--no-lock` is for a HUMAN who has confirmed sole use of the board.
> It is NEVER for a script, and NEVER for working around a stuck lock.**

The second half is the one that matters operationally: **`flock` is
kernel-owned, so a lock that will not open always means a live holder.** There
is no stale state to clear, so "the lock is stuck" is not a diagnosis — it is a
misreading, and `--no-lock` would then be two tools on one board. The rule is
printed by the banner itself (`NOLOCK_RULE`, `sw/board_lock.py:125`) and
repeated in `docs/USAGE.md:509`.

Phase 6 measures all of it: the escape gets past a live holder, shouts on both
streams, says another holder was present, leaves the audit line, and **does not
take the lock** (the holder's identity block is still the holder's afterwards).

---

## §7 Stale-lock policy: there are none, by construction

`flock` is released by the kernel when the last fd on it closes — including
SIGKILL, a dropped ssh, or a crash. **So there is no stale lock, and
`sw/board_lock.py` deliberately has no `--force-unlock`**; phase 4 asserts its
absence from `--help` so nobody adds one quietly.

What *can* go stale is the 256-byte identity **text**, which a killed holder
does not get to truncate. The two are told apart by probing the lock itself:

| situation | `--status` |
|---|---|
| live holder | `HELD` + the block + whether the named pid is alive here |
| holder SIGKILLed | `not held — the identity block below is STALE (a killed holder cannot truncate it; the kernel released the flock)` |
| never taken here | `no lock file yet` |
| lock unprobeable | `UNKNOWN — treat the board as taken and ask a human` |

A successful `acquire()` truncates and rewrites the block, so stale text never
survives one acquisition. Phase 4 SIGKILLs a real holder and measures every row
of that table, including that the next acquire succeeds and overwrites the dead
holder's block.

**Failure semantics, stated because the tools must not be brickable by their
own lock** (`sw/board_lock.py:343`):

- **contention** → REFUSE, naming the holder. That is the point.
- **the lock file is unusable** → REFUSE, naming the errno *and* both escapes.
  Fail-**closed** on purpose: a lock that quietly evaporates when the
  filesystem hiccups is worse than no lock, because people start trusting it.
  This costs nothing new — the lock has always been on the same NFS mount as
  the tools themselves.
- **anything else** → still `BoardLockError`. Nothing but that class escapes
  `acquire()`, so a lock-layer bug can never surface as a traceback mid-session.
- **`release()` never raises.** A shutdown-time lock problem must not mask a
  run's real result.
- **cost**: one `open`, one `flock`, one `fsync`, one `git rev-parse`, **once**,
  at process start, before any device fd. **Nothing on the per-step decode
  path** — the lock is held, not re-checked. Measured: 0.004–0.005 s.
- **`acquire()` is idempotent** and `__exit__` always releases, so a tool may
  refuse early and still write `with lock:` around its session body.

---

## §8 The regression floor

`sw/` is the 2B production path and this task edits ten of its tools, so the
floor is measured, not assumed. On **snoke**, after every edit:

| gate | result |
|---|---|
| `BOARDFREE` (`make seq_selftest serve_test` + `chat_seq --selftest`) | **BOARDFREE_PASS** — `seq_run` **2758**, `serve` **85**, `chat_seq` **357** |
| `evidence/qwen2b/rc/t4_bytes_unmoved.sh` | **BYTES_UNMOVED PASS** — 15 weight images, 0 differ |
| `ref/scripts/regen_gate.sh` | **REGEN_GATE_PASS**, sha `a69864d2…`, 60,495 records |
| `evidence/qwen9b/g2/final_bytelock_pin.sh` | **FINAL_BYTELOCK_PIN PASS** — 54 rows, 0 bad |
| `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` | **SPEC_CITES_REGRESSION PASS** — all eight pinned documents at their pinned counts |

### §8a Re-run on the committed tree

Every gate above was produced while the tree was dirty, so all of it was
re-run on the commit itself. **`=== tree: 1a6565a`, no `+dirty` flag, nothing
untracked left** (the wrapper's dirty flag reports tracked modifications only —
G2b's finding — so this is the run that closes it):

| log | host | result |
|---|---|---|
| `20_gate_snoke_committed.log` | snoke | **O3_LOCK_GATE PASS**, 93 passed / 0 failed / 1 skipped (the one-way ssh) |
| `25_gate_darthplagueis_committed.log` | darthplagueis | **O3_LOCK_GATE PASS**, **101 / 0 / 0** — cross-host proven in both directions |
| `21_boardfree_committed.log` | snoke | **BOARDFREE_PASS** — 2758 / 85 / 357 |
| `22_bytes_unmoved_committed.log` | snoke | **BYTES_UNMOVED PASS** |
| `23_regen_gate_committed.log` | snoke | **REGEN_GATE_PASS** |
| `24_final_bytelock_pin_committed.log` | snoke | **FINAL_BYTELOCK_PIN PASS** |

> **CORRECTION 2026-09-01 (review F12): commit `a77a819`'s subject says
> "snoke 93/93".** The run is **93 passed / 0 failed / 1 skipped** — snoke has
> no ssh key to darthplagueis, so the peer half of phase 3 reports SKIPPED
> with its reason there instead of silently passing, and both directions are
> covered by the darthplagueis run. The table above and §3 always said this;
> the commit subject rounded it. A commit message cannot be amended after the
> fact, so the correction lives here, where the gate is read.

`chat_seq`'s selftest went **351 → 357**: six new checks, none removed. They are
in block `[11]`, which now checks the **path** as well as the flock — that
`SeqLock` is a `BoardLock`, that it still raises `ChatSeqError`, that
`LOCK_PATH` is the shared file and **not** inside `SW_DIR`, that the superseded
path is still named and *is* local, and that the identity block carries all
five fields. The old block could not have caught this defect, because it only
ever tested a lock against itself.

### §8b Fix round 1 — the floor re-measured, and the whole log index

Every gate in §8 was re-run after the twelve findings were fixed, because the
round edits `sw/board_lock.py`, three shell tools and the gate itself. **The
floor did not move**: identical numbers to `1a6565a`, which is the claim worth
making — none of the corrections changed what any tool emits.

| gate | host | result | log |
|---|---|---|---|
| `BOARDFREE` | snoke | **BOARDFREE_PASS** — `seq_run` **2758**, `serve` **85**, `chat_seq` **357** | `47_boardfree.log` |
| `evidence/qwen2b/rc/t4_bytes_unmoved.sh` | snoke | **BYTES_UNMOVED PASS** — 15 weight images, 0 differ | `48_bytes_unmoved.log` |
| `ref/scripts/regen_gate.sh` | snoke | **REGEN_GATE_PASS** — 60,495 records | `49_regen_gate.log` |
| `evidence/qwen9b/g2/final_bytelock_pin.sh` | snoke | **FINAL_BYTELOCK_PIN PASS** — 54 rows, 0 bad | `50_final_bytelock_pin.log` |
| `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` | snoke | **SPEC_CITES_REGRESSION PASS** — all eight pinned documents at their pinned counts | `51_spec_cites_regression.log` |

`FABLE5_RS_F` is **not** exported across `t4_bytes_unmoved.sh` or
`ref/scripts/regen_gate.sh` (plan amendment A2.5) — each log's wrapper header records
`FABLE5_RS_F=unset`, so that is checkable rather than asserted.

**The whole fix-round log index**, in the order it was produced. Logs `00`–`25`
are the original round and are untouched; nothing here was re-run in place.

| log | host | what |
|---|---|---|
| `30_cite_drift_check.log` | dp | RED — `O3_CITE_DRIFT CHECK FAIL (88 drifted, 0 unresolved, 0 missing)` |
| `31_cite_drift_verify.log` | dp | GREEN — `O3_CITE_DRIFT VERIFY PASS (0 problem(s))` |
| `32_…negcontrol_check.log` | dp | control — `CAUGHT (109 reported)` |
| `33_…negcontrol_verify.log` | dp | control — `CAUGHT (88 complaints)` |
| `34_doc_cites_check.log` | dp | RED — `O3_DOC_CITES CHECK FAIL (14 drifted of 32)` |
| `35_doc_cites_verify.log` | dp | GREEN — `O3_DOC_CITES VERIFY PASS (0 problem(s))` |
| `36_…negcontrol_check.log` | dp | control — `CAUGHT (14 reported)` |
| `37_…negcontrol_verify.log` | dp | control — `CAUGHT (14 complaints)` |
| `38_board_lock_selftest_darthplagueis.log` | dp | `BOARD_LOCK_SELFTEST PASS` 38/38 |
| `39_board_lock_selftest_snoke.log` | snoke | `BOARD_LOCK_SELFTEST PASS` 38/38 |
| `40_gate_darthplagueis.log` | dp | the first full pass, **127 / 0 / 0** — before phase 7 gained the nine F1 shape checks |
| `41_gate_snoke.log` | snoke | the same, **119 / 0 / 1** |
| `42_spec_cites_board_lock.log` | dp | **RED, and it is this round's own doing**: the new prose put 25 citation defects into this document — five bare tool basenames, four AMBIG rows in §9.1's table, two ORPHAN continuations, one false QUOTE. Kept as the capture |
| `43_spec_cites_spec.log` | dp | `SPEC CITES: PASS` (the spec) |
| `44_spec_cites_plan.log` | dp | `SPEC CITES: PASS` (the plan) |
| `45_spec_cites_other_gate_docs.log` | dp | the seven other documents this round touches; every count is at or **below** its `a77a819` value — GPTQ 7 → 6, W8_SKETCH 4 → 3, RC_GATE 27, RD_GATE 8, TIMING 16, G2C_CHAIN 0, QWEN35_NEXT_FEASIBILITY 128; the non-zero ones are pre-existing and pinned) |
| `46_spec_cites_selftest_plan.log` | dp | `SELFTEST: PASS`, six controls CAUGHT, with the plan's path passed explicitly |
| `47_…`–`51_…` | snoke | the regression floor (table above) |
| `52_spec_cites_board_lock_fixed.log` | dp | GREEN — `SPEC CITES: PASS`, 177 exist / 47 range / 2 quote, `FAIL 0` |
| `53_gate_darthplagueis_final.log` | dp | **136 / 0 / 0** — with phase 7's nine F1 shape checks, before phase 6 gained the two escape-propagation checks |
| `54_gate_snoke_final.log` | snoke | the same, **128 / 0 / 1** |
| `55_gate_darthplagueis_final2.log` | dp | the whole gate after every fix, **138 / 0 / 0**, cross-host both directions |
| `56_gate_snoke_final2.log` | snoke | the same, **130 / 0 / 1** (snoke cannot ssh darthplagueis; reported SKIPPED with its reason, never silently passed) |
| `60_…`–`69_…` | both | all of it again on the **committed** tree — §8c |

### §8c Fix round 1, re-run on the committed tree

Everything in §8b was produced on a dirty tree, so all of it was re-run on the
commit itself: **`=== tree: 77584e9`, no `+dirty` flag, nothing untracked
left.** `FABLE5_RS_F=unset` in every header (plan amendment A2.5).

| log | host | result |
|---|---|---|
| `60_gate_darthplagueis_committed.log` | dp | **O3_LOCK_GATE PASS**, **138 / 0 / 0** — cross-host proven in both directions |
| `61_gate_snoke_committed.log` | snoke | **O3_LOCK_GATE PASS**, 130 passed / 0 failed / **1 skipped** (the one-way ssh, §3) |
| `62_boardfree_committed.log` | snoke | **BOARDFREE_PASS** — 2758 / 85 / 357, identical to `1a6565a` |
| `63_bytes_unmoved_committed.log` | snoke | **BYTES_UNMOVED PASS** — 15 weight images, 0 differ |
| `64_regen_gate_committed.log` | snoke | **REGEN_GATE_PASS** |
| `65_final_bytelock_pin_committed.log` | snoke | **FINAL_BYTELOCK_PIN PASS** — 54 rows, 0 bad |
| `66_spec_cites_regression_committed.log` | snoke | **SPEC_CITES_REGRESSION PASS** — all eight pinned documents at their pinned counts |
| `67_cite_drift_verify_committed.log` | dp | **O3_CITE_DRIFT VERIFY PASS (0 problem(s))** |
| `68_doc_cites_verify_committed.log` | dp | **O3_DOC_CITES VERIFY PASS (0 problem(s))** |
| `69_spec_cites_board_lock_committed.log` | dp | **SPEC CITES: PASS** on this document |

**The floor did not move.** Every number is the one `1a6565a` produced; the
twelve corrections changed no byte any tool emits.

---

## §9 Citation drift, which this task caused and had to close

Editing ten `sw/` files moves lines that the spec, the plan and five gate
documents cite by number, and `spec_cites.py` **cannot see that class**: a
QUOTE check fires only when the quotation shares a markdown line with its cite,
so a citation that drifts but stays in range passes silently. This campaign has
been bitten by it three times already (G2a's `c366b3a`, G2c's off-by-one,
G2b's stale batch).

`evidence/qwen9b/o3/o3_cite_drift.py` answers it mechanically: a
`difflib.SequenceMatcher` old→new **line map** per edited file, and the citation
sweep taken from the **committed** document tree (`dc8f492`) rather than the
working tree — which is what makes it reproducible *after* the fix, since
"where did the line this document used to name go?" has one answer forever.

A **bare continuation** — `` `:NNN` `` on a line that already names a file —
is a citation too, and the weakest kind: `evidence/qwen_next/spec_cites.py` can
call it ORPHAN or AMBIG but cannot see that it moved. They are swept and
renumbered with the map of the one file their line names.

> **CORRECTION 2026-09-01 (review F6): the sweep had two holes, and the
> gate could not see either of them.** (a) It swept only `.md`/`.txt`, so
> **five citations inside code comments** — `tb/tb_seq_chip.sv:88`,
> `sw/hwmap.py:235` (twice), `ref/gen_layer_script.py:1116`,
> `evidence/qwen2b/rc/t4_wall8_probe.py:11` — were never looked at. (b) A
> bare continuation was bound only when its line carried a **full**
> `sw/<f>.py:NNN` token, so a line that merely *names* the file and then
> writes a bare `:NNN` continuation bound to nothing. That is how `plan:809` came to
> carry `:1744` meaning the OLD line and `sw/chat_seq.py:1744` meaning the
> NEW one **in one sentence**. Both are closed: the sweep now covers
> `.py`/`.sh`/`.sv`/`.v`/`.tcl` under `rtl/ sw/ ref/ tb/ evidence/ synth/`,
> and `NAMED` is computed from bare mentions as well as from cites. The
> numbers below are from the widened sweep, which is why they are larger
> than the ones the first round reported (103 / 21 / 82).

**Result [D]:** **109** distinct `(file, line)` citations into the twelve
edited files. **21 unmoved, 88 drifted, 0 unresolved, 0 missing.** All 88
renumbered and verified: the new line's content equals the base content of the
old line, the citing document names the new number, and no document still names
the old one.

### §9.1 The other half of the class: citations into the **documents** this task edited

**Also review F6, and the sw/-only sweep is structurally blind to it.** O3
edits `docs/USAGE.md`, `docs/ARCHITECTURE.md` and `docs/HISTORY.md`, and
inserting lines into a document moves the lines *other* documents cite in it.
`docs/HISTORY.md` got a 20-line dated preamble, so **every** citation into it
below line 21 moved by exactly 20; `docs/USAGE.md` grew by 111 lines.

`o3_cite_drift.py --doc-cites` answers it with the same machinery and the same
discipline — the citing files are swept from `dc8f492`, never from the working
tree, so a citation this round rewrote is still checked rather than becoming
invisible. **The targets are derived, not listed**: every `.md`/`.txt` whose
*line count* moved between the base and the worktree, so the next task that
edits a document is covered without editing the gate. It is **check-only**: a
document citation carries no `sw/`-style file token to key a rewriter on, and
fourteen hand-fixes verified against base content are safer than a rewriter
nobody has exercised.

**Result [D]:** **32** line numbers cited into the three documents at
`dc8f492`; **18 unmoved, 14 drifted**, all 14 repaired and verified. They were
in five files, and one of them is a gate script rather than prose:

| citing file | was | now |
|---|---|---|
| `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md` (×2) | `docs/USAGE.md:478-482` | `docs/USAGE.md:588-592` |
| `ref/scripts/regen_gate.sh` — **the emitter-hash gate itself** | `docs/USAGE.md:478-482` | `docs/USAGE.md:588-592` |
| `docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md` | `docs/USAGE.md:463-477` | `docs/USAGE.md:573-587` |
| `evidence/qwen9b/g2/G2C_CHAIN.md` | `docs/USAGE.md:244` | `docs/USAGE.md:269` |
| `evidence/qwen2b/rb/TIMING.md` (×5) | five `docs/HISTORY.md` numbers 128, 150, 214, 220 and 243 | `docs/HISTORY.md:1099`, `docs/HISTORY.md:1121`, `docs/HISTORY.md:1185`, `docs/HISTORY.md:1191`, `docs/HISTORY.md:1214` |

The `evidence/qwen2b/rb/TIMING.md` row's **comma** continuation is worth
naming: a `docs/HISTORY.md` mention carrying two numbers separated by a comma is a
third form of bare citation, and the first cut of `--doc-cites` matched only
the first of the pair — it saw the 128 of "128, 150" and not the 150. Both
numbers are parsed now. **Written out of citation form on purpose** (2026-09-14):
those two numbers are the PRE-repair values this section is about, so a
renumbering pass must not "repair" them — the tool's own docstring names this
class ("an example, not a citation").

> **RENUMBERED 2026-09-14 (Task 16, G7), and O3's own repair is preserved
> here rather than in the row.** O3 repaired `evidence/qwen2b/rb/TIMING.md`'s
> five numbers to `docs/HISTORY.md` lines 148, 170, 234, 240 and 263 — written
> as bare numbers here, out of citation form, because they are a record of
> where those lines WERE — and that is what this table's third column read
> until the ship. The ship
> then moved the whole `NEXT_SESSION.md` dated stack into `docs/HISTORY.md`,
> which pushed every line below the file's header down by **736**, so the
> third column is renumbered above to `884` / `906` / `970` / `976` / `999` —
> the SAME five lines, under their new numbers. `evidence/qwen2b/rb/TIMING.md`
> itself was repaired in the same pass. RED
> `evidence/qwen9b/o3/123_g7_doc_cites_check_RED.log`, GREEN
> `evidence/qwen9b/o3/125_g7_doc_cites_verify2.log`.

### §9.2 Evidence

- RED `30_cite_drift_check.log` — `O3_CITE_DRIFT CHECK FAIL (88 drifted...)`
- GREEN `31_cite_drift_verify.log` — `O3_CITE_DRIFT VERIFY PASS (0 problem(s))`
- negative controls `32_cite_drift_negcontrol_check.log` and
  `33_cite_drift_negcontrol_verify.log` — **both CAUGHT** (`--check` compared
  one line off, 109 reported; `--verify` demanded a deliberately wrong target,
  88 complaints)
- RED `34_doc_cites_check.log` — `O3_DOC_CITES CHECK FAIL (14 drifted of 32)`
- GREEN `35_doc_cites_verify.log` — `O3_DOC_CITES VERIFY PASS (0 problem(s))`
- negative controls `36_doc_cites_negcontrol_check.log` and
  `37_doc_cites_negcontrol_verify.log` — **both CAUGHT**
- `evidence/qwen_next/spec_cites.py`: **PASS** on the spec, the plan, this gate
  doc and every other gate document this round edits;
  `SPEC_CITES_REGRESSION PASS` with all eight pinned documents back at their
  pinned counts.

**Three defects in the fixer itself, recorded because they are the same mistake
three times** — treating a renumber as a sequence of independent replacements
(`evidence/qwen9b/o3/o3_cite_drift.py`, `rewrite_doc`):

1. **sequential collision** — in `sw/tok_meter.py`, line 487 moved to 500 and
   line 500 moved to 513 (**numbers as they stood at `dc8f492`**, hence written
   as prose here rather than as citations). The first rewrite was applied, and
   then the second was applied to the same document and moved the token the
   first had just written;
2. **half-fixed ranges** — a `sw/chat_seq.py` range of 1094-1100 matched the
   start-of-range pattern only and became 1074-1100: a range whose start had
   moved and whose end had not;
3. **stale bare continuations** — `docs/QWEN35_NEXT_FEASIBILITY.md` carries a
   row that names a four-line `sw/infer.py` span and then repeats four bare
   continuations for the same four lines. Renumbering only the full token left
   those four pointing at the old lines: **a document that contradicts itself,
   which is worse than one that is uniformly stale.** The row now reads
   `sw/infer.py:798-802` with continuations `:798`, `:799`, `:800`, `:802`.

Blast radius each time was eleven documents including three other gates'
committed evidence, so each repair was `git checkout` plus a redo rather than a
patch on top. The rewriter is now line-scoped and single-pass: full tokens,
both range endpoints, and continuations, all mapped in one traversal.

**What this method does NOT promise, stated because a review asked for it
(F6).** The guarantee is *"the citation names the same code as before"*, not
*"the citation is correct"*. A citation that was **already wrong at
`dc8f492`** is faithfully moved to a new wrong line, and **two** such are in
the tree. Both are recorded here rather than repaired, because repairing
either means restating another owner's finding, not renumbering a line.

**(1) The plan's and the spec's per-op-vector-lengths row.** The plan bullet
now reads `sw/chat_seq.py:1724`, `:1726`, `sw/chat_seq.py:1736`,
`sw/chat_seq.py:1739`, `sw/chat_seq.py:1742`, `sw/chat_seq.py:1744`, `:1746`
and the spec's §7.4 row the same. Every one of those is the faithful image of
the number it carried at `dc8f492` — verified line by line — **and every one
of them was already pointing at `HostHeadTopK.__init__` and `read_x8_eout`
rather than at any vector length.** The decoder the row is about is
`_scratch_footprint`, whose docstring is at `sw/chat_seq.py:1818` and whose
per-op lengths run from `sw/chat_seq.py:1842` — and its own text records that
**G2a already did the work the row asks for**: *"the per-op vector LENGTHS
below used to be the literals 128 / 256 / 16 / 32, which are `LDK`/`LDV`,
`HD`, `LNH` and `2*LNH`"*. So the row is stale in its numbers *and* closed in
its substance. Re-pointing it would be a disposition on a 9B work item, which
is the campaign owner's call and not a lock task's.

**(2) The defect-B row.** `docs/QWEN35_NEXT_FEASIBILITY.md`'s defect-B row and
`evidence/qwen_next/defect_a/defect_b_probe.py` quote four `M.vnw_(STG,
1024)` / `M.vn` / `M.alu` / `M.matvec` lines at `sw/infer.py:797-801`, but
those numbers were comments and a `gold =` assignment **at `dc8f492` too** —
the code they describe moved when G2a (`b2f1223`) generalized the head path,
and it now reads `M.vnw_(STG, LR.H)` at `sw/infer.py:827` and
`M.matvec(self.qw_head, X8, LR.H, …)` at `sw/infer.py:836`. This task moved
the row to `sw/infer.py:798-802` because that is where those *lines* went, and
**deliberately did not re-point it**: whether defect B is closed is Track F's
statement to make in Track F's evidence, not a side effect of a lock task's
renumbering. Recorded in §10 as a residual.

**Verified before touching them (the standing ORCHESTRATOR RULE):**
`git diff --stat` on every document was empty — no other task's uncommitted
work was in any of them, checked rather than assumed. No other task is live.

---

## §10 NOT ESTABLISHED

1. **The board was not touched, so nothing here is measured on silicon.** The
   real reprogram sequence under the lock — `sw/program_fpga.sh` doing remove →
   JTAG → rescan for real — is **T15's** to exercise. What is proven is that
   the lock is held across it and that a second holder is refused; the vivado
   and `sudo -n pcie_helper.sh` steps inside it were not run by this gate.
2. **`sw/program_fpga.sh` changed behaviour** and that change is untested on
   hardware: it now runs remove/rescan by default (previously the caller's job)
   and it now **exits non-zero when `PROGRAM_OK` is absent** (previously it
   always exited 0). T15 should read this paragraph before its first reprogram.

   > **CORRECTION 2026-09-01 (review F1).** An earlier revision of this row
   > said *"the rescan still runs even when the program fails"*. **That was
   > only true of one exit path.** The rescan was written inline after the
   > vivado call, so a `set -e` abort anywhere before it — the
   > Vivado settings64.sh source, `$PCIE remove` itself, a SIGINT — skipped it,
   > and `--jtag-only` never rescanned at all (by design: the caller owns
   > it) while `sw/stage1_hw_bringup.sh` had `set -e` and **no trap**, so it
   > aborted between its own remove and its own rescan. Either way the
   > endpoint was left **off the PCI tree with the lock released on
   > unwind** — the board then looks dead to `lspci` and to every tool, and
   > the next person reaches for a power cycle. Fixed: `sw/program_fpga.sh`,
   > `sw/stage1_hw_bringup.sh` and `sw/test_ctl.sh` each rescan from an
   > `EXIT INT TERM` trap, so **every** exit path puts the endpoint back,
   > and each reports loudly if the rescan itself fails.

3. **A JTAG failure does not mean the FPGA changed.** A run that never starts
   configuration leaves the **OLD bitstream** in the device, and it
   re-enumerates and answers CSR reads perfectly normally — so nothing
   downstream looks wrong. **The exit code is the only staleness warning
   there is.** `sw/program_fpga.sh` now says so on the failure path in as many
   words, and T15 must verify the CSR `VERSION` against the build it meant
   to load before any DMA. This is not a new hazard; it was simply never
   written down.
4. **A checkout that has not picked up this commit is not protected.** The other
   working tree on this machine (`grok46_llm/fable5`, branch `grok46-qwen2b` at
   `8ad8be0`) still locks its own `sw/.seq.lock` until it merges. **The lock
   cannot protect anyone from code that does not take it.** This is the honest
   residual and it is stated in `docs/USAGE.md` §5 as well.
5. **Cross-host exclusion is proven for snoke↔darthplagueis only**, because
   those are the two hosts that mount the export and can reach the board. It is
   not proven from kyloren/fn2187/darthvader, and no lock file was created
   there.
6. **`--no-lock`'s audit log is best-effort.** If `<lock>.nolock.log` cannot be
   written the tool still runs; the banner is the guarantee, the file is the
   convenience.
7. **The `<lock>.nolock.log` audit file is unbounded and unrotated.** It is a lab tool; nobody has
   decided what to do when it grows.
8. **`sw/cycle_census.py` and `sw/mover_bench.py` gained `--dev`** so they could be
   pointed away from the board — previously hard-coded. That is a real
   behavioural surface this gate exercised only with a nonexistent path.
9. **No measurement of contention under load.** The lock is taken once per
   process; the 0.004–0.005 s figure is a single acquire on an idle NFS mount,
   not a distribution.
10. **THE LOCK IS PER-TOOL, NOT PER-LIBRARY, and that is a real residual
    (review F8).** `sw/seq_run.py`'s `Dev.__init__` and
    `sw/chat_seq.py`'s `open_board()` do **not** lock — the ten adopting
    tools take the lock in `main()`, so **anything that imports the library
    and constructs `Dev` directly bypasses it.** Five in-repo scripts do
    exactly that and are runnable today:
    `evidence/qwen2b/rd/rd_census.py`, `rd_residency_audit.py`,
    `evidence/qwen2b/rd/rd_zero_scratch.py` (**destructive** — it zeroes the whole scratchpad),
    `evidence/qwen2b/rd/rd_identity.py`, and
     `evidence/qwen2b/rd/rd_program_035.sh` (a bare `pcie_helper`
    remove/rescan around a reprogram). They are **frozen R-d evidence and
    were NOT rewritten**; each now carries a dated header naming the lock
    and the `--exec` one-liner that wraps it. Locking inside `Dev` is the
    obvious next move and is **not taken here**: it would change the
    behaviour of committed evidence scripts under a gate that cannot run
    them, and `Dev` is constructed in board-free selftests too.
11. **`--exec`'s argv split is positional, not clever.** Everything after
    the first bare `--` is the wrapped command and is never parsed as
    `sw/board_lock.py`'s own option (review F9: `parse_known_args` used to eat
    a `--lock`/`--tool`/`--status` belonging to the *wrapped* tool, so
    `--exec -- mytool --status` ran board_lock's `--status` and never
    launched `mytool`). A wrapped command that itself needs a literal `--`
    argument still needs care.
12. **`probe_state` returns `unknown`, not `free`, for a uid that cannot
    write the lock file** (review F11). The probe needs an `O_RDWR` fd
    because a POSIX write lock over NFS is refused on a read-only one, so a
    reader outside the owning group sees `unknown` — and would also fail to
    acquire. `--status` now says this in as many words. The file is created
    `0666`; only its directory's permissions can defeat that.
13. **TWO citation clusters in the tree are stale in MEANING and were
    deliberately left that way** (§9's closing paragraphs), because
    repairing either is a disposition on somebody else's work item rather
    than a renumbering. (a) The **plan's and the spec's** per-op-vector-
    lengths row names `sw/chat_seq.py:1724`…`:1746`, which is the faithful
    image of what it said at `dc8f492` and was **already** pointing at
    `HostHeadTopK.__init__` / `read_x8_eout`; the decoder it means is
    `_scratch_footprint` at `sw/chat_seq.py:1818` onward, and **G2a already
    derived those literals from the geometry**, so the row is also closed in
    substance. (b) `docs/QWEN35_NEXT_FEASIBILITY.md` and
    `evidence/qwen_next/defect_a/defect_b_probe.py` name
    `sw/infer.py:798-802` for code that lives at `sw/infer.py:827`/`:836`
    and no longer contains the `1024` the defect was about — **Track F's**
    statement to make. **Neither `--check` nor `--doc-cites` can catch this
    class**: a citation that was wrong *before* the base commit is wrong
    **at** the base, and every method here is anchored to the base. The only
    thing that catches it is a human reading the cited line against the
    claim beside it. **That was NOT done for all 141 citations** — it was
    done for this gate document's own (§11) and for the two clusters a
    reviewer pointed at. The rest are proven to name the same code they
    named at `dc8f492`, and nothing stronger.
14. **The shell tools are RED-only in the gate.** `sw/program_fpga.sh`,
    `sw/stage1_hw_bringup.sh` and `sw/test_ctl.sh` are proven to REFUSE under
    contention before their first `sudo`; the GREEN half — that they get
    *past* a free lock and do the right thing — cannot be run without
    `pcie_helper.sh remove` and vivado. **T15 owns it.** What phase 7 pins
    instead is the SHAPE that makes F1's fix true — an `EXIT INT TERM` trap,
    a rescan inside it, and the arming flag set *before* the remove — three
    checks per script. That is a regression against the specific defect, not
    a proof that the sequence works: **the traps have never fired on
    hardware.**

---

## §11 Files

**Created:** `sw/board_lock.py`; `evidence/qwen9b/o3/{BOARD_LOCK.md,
o3_red_percheckout.py, o3_lock_gate.py, o3_cite_drift.py}` and their logs.

**Modified:** `sw/{chat_seq,serve,cycle_census,seq_run,infer,tok_meter,
mover_bench,layer_test,matvec_test,ddr_test}.py`,
`sw/{program_fpga,stage1_hw_bringup,test_ctl}.sh`,
`docs/{USAGE,ARCHITECTURE,HISTORY}.md`, plus the documents whose citations
this task's edits moved (§9, §9.1), each named individually in the commit.

**Added in fix round 1 (review of `1a6565a`+`a77a819`):** `sw/test_ctl.sh`
(F2); dated header comments on the five frozen R-d scripts that construct
`SR.Dev` or drive `pcie_helper` with no lock (F8) —
`evidence/qwen2b/rd/{rd_census,rd_identity,rd_residency_audit,
rd_zero_scratch}.py` and `evidence/qwen2b/rd/rd_program_035.sh`, **header comments only, no logic
touched**; the five code files carrying `sw/…:NNN` citations the widened sweep
found (`tb/tb_seq_chip.sv`, `sw/hwmap.py`, `ref/gen_layer_script.py`,
`evidence/qwen2b/rc/t4_wall8_probe.py`,
`evidence/qwen_next/defect_a/defect_b_probe.py`); and the five files carrying
document→document citations (§9.1) —
`docs/superpowers/plans/2026-08-12-qwen2b-track-r.md`,
`docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md`,
`evidence/qwen2b/rb/TIMING.md`, `evidence/qwen9b/g2/G2C_CHAIN.md`,
`ref/scripts/regen_gate.sh`.

`docs/HISTORY.md` is a log — *"VERBATIM as it was written at the time"* — so its
two entries carrying the open "flock retrofit" follow-on were **not edited**. A
dated supersession note was appended to the preamble instead, naming both
entries and stating what in them is now wrong.
