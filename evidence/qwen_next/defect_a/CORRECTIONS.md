# Track F / defect A — corrections to the first evidence round

Dated notes. The **fix** (`ref/seq_chat.py`, commits `2a50cac` + `22f7ca8`) was
correct and remains correct; what follows are claims *about* it that the first
round got wrong, found by scoped re-review. Commit messages are immutable, so
this file is where they are corrected — read it beside `run.log`.

---

## 2026-08-25 — C1: "loud at H=2560" was an artefact of the test (review F1)

**Claimed** (first-round `ref/seq_chat.py:1515-1517` and the `2a50cac` commit
message): at H=2560 the pre-fix reader *raises* — "loud at this geometry".

**Wrong.** That was manufactured by the regression's synthetic vocabulary,
which was **V=37, odd**. With an odd V, `V*2*H // 2048` floors at H=2560 and
the reshape becomes illegal. The real vocabulary is **248,320 — even** — and
`248,320 * H` is a multiple of 1024 for **every even H**, so the pre-fix
`reshape(n, 1024)` is **legal and silent at all four geometries**:

| model | H | file bytes | pre-fix rows | `n*1024` | `V*H` | rows vs vocab |
|---|---|---|---|---|---|---|
| 0.8B | 1024 | 508,559,360 | 248,320 | 254,279,680 | 254,279,680 | **1x** |
| 2B | 2048 | 1,017,118,720 | 496,640 | 508,559,360 | 508,559,360 | **2x** |
| 4B | 2560 | 1,271,398,400 | 620,800 | 635,699,200 | 635,699,200 | **2.5x** |
| 9B | 4096 | 2,034,237,440 | 993,280 | 1,017,118,720 | 1,017,118,720 | **4x** |

The study was right and the first-round fix docs contradicted it:
`docs/QWEN35_NEXT_FEASIBILITY.md` §2.10 (:678) already said `vocab = nrow`
goes **"2.5x/4x too large"** — precisely the last column.

**Closed by**: the regression now uses an **even** synthetic V (40) and, before
touching any file, checks the arithmetic at the **real** `vocab_size` straight
out of the config (`real vocab ... the pre-fix reshape is LEGAL`). The
`old is None` / "loud at this geometry" branch is gone. The pre-fix model is
also now compared against the **flat** buffer rather than per-row, because at
H=2560 a pre-fix row straddles two tokens (20 of 100 rows in the synthetic
table do) — the first-round per-row model was itself wrong there.

## 2026-08-25 — C2: the defect-B "max|diff| 1" was one lucky sample (review F4)

**Claimed** (first-round `sibling_2b.log`, and repeated in the ledger): the
three silently-wrong lines before defect B's crash change the leading half of
the residual by `max|diff| 1`, and the DYNQ8 exponent is unchanged.

**Understated.** That was a single i.i.d.-uniform residual, where both halves
carry equal energy and RMSNorm's denominator barely moves. RMSNorm's
denominator is a mean over the words it is *told* about, so the error scales
with how unevenly the residual's energy is split. Re-measured, both ways, in
`sibling_2b.log`:

| residual | half-energy lo / hi | DYNQ8 exp (n=H / n=1024) | max\|diff\| | mean\|diff\| | words changed |
|---|---|---|---|---|---|
| i.i.d. uniform | 53,101 / 52,562 | 0 / 0 | **1** | 0.1 | 120/1024 (11.7 %) |
| uneven (hi 6x lo) | 52,467 / 1,833,036 | **1 / 0 (shifted)** | **99** | 48.6 | **1020/1024 (99.6 %)** |

The reviewer's independent draw gave max 108 / mean 54.9 / 99.5 % — same
phenomenon. **The honest statement**: the silent error before the loud crash is
near-zero only when the halves happen to carry equal energy, and is essentially
total when they do not. Nothing about defect B's *severity verdict* changes —
it still crashes at the matvec — but "loud" describes where it stops, not where
it starts going wrong.

## 2026-08-25 — C3: the fix's own manifest-less fallback (review F2)

The first round's `emb_row_bytes()` fell back to `2*LR.H` when no
`<base>.weights.json` existed, and `layer_fixed_greedy` passed `base=None` for
any path not ending in `.emb.bin`, which **skipped the manifest entirely**.
With no vocabulary cross-check anywhere, that path reshaped whatever it was
handed — defect A, reproduced inside the fix, reachable through the documented
`--base` CLI.

**Closed by**: the manifest is now **required** (as `ref/seq_model.py:1297-1303`
requires it); `emb_base_of()` refuses a path that is not `<prefix>.emb.bin`
instead of returning `None`; and `load_emb` cross-checks the row count against
the selected config's `vocab_size`. Four new deliberate-damage cases cover it
(no manifest, other-geometry manifest, wrong vocab, mis-named path).

## 2026-08-25 — C4: the first round's check count was not reproducible (review F3)

`selftest_08b.log` recorded **50/50 ok** against sha `22f7ca8`, but that tree
also carried Track L's *uncommitted* `ref/model_select.py` with the 4b/9b
entries; from `22f7ca8` alone the count is **48**. Not a wrong result — the
count is data-dependent by design, since the regression runs once per
`model_select.MODELS` entry — but it was not self-disclosing.

**Closed by**: `run.sh` now captures `git status --porcelain` into `run.log`
before the first check, so any dirty-tree run says so on its face.

## 2026-08-25 — C5: "five lines after :1247" is 13 (review F9)

`2a50cac`/`22f7ca8`'s messages and the study both say the correct
`M.embed(tok, GLS.X0, LR.H)` sits "five lines after :1247" from the four
hard-coded `1024`s. It is **13** lines (:1247 -> :1260).
