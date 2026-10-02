# R3-1 — ISA: SEQ_ISA B17.3, the MOVX broadcast, and the SEQ_CAPS r3 bit

Task R3-1 of the R3 campaign (`docs/superpowers/plans/2026-09-29-r3-broadcast.md`,
Task R3-1; the user's ruling 2026-09-29: R3, form (a), the direct x-push bus).
Contract and its test only: **no RTL, no host row, no hwmap edit, no build, no
board.** Every run below is on snoke through `evidence/qwen9b/sr/sr_run.sh`
with /home/cah/.venv/bin/python, log block n2300–n2399.

## 1. The contract — `docs/SEQ_ISA.md` §B17.3

B17.3 was a four-line reserved stub ending the file (`docs/SEQ_ISA.md:1589-1592`,
kept verbatim, including its "NOT BUILT; ruled A (form (a)) 2026-09-29" status
line, which stays until R3-10). The contract is APPENDED after it, so no line
of the file moved (the only hunk is `@@ -1592,0 +1593,100 @@`,
`evidence/qwen9b/sr/n2305_r3_1_seqisa_hunkhdr.log:6`).

| what | where |
|---|---|
| CONTRACT: transcribes spec §1.3 (a) and §1.4, adds nothing; NOT BUILT; the R3 RTL does not exist yet (R3-8's); every RTL line cited is today's; the TDD ties it | `docs/SEQ_ISA.md:1594-1603` |
| Semantics: one scratch read, the same x into all four XWINs at the same words (OV1 census) | `docs/SEQ_ISA.md:1605-1607` |
| Encoding table: MOVX flags[7:4] 0xF = broadcast; 4..14 reserved err 0x05; MVGO 0xF err 0x05 (MOVX only); flags[3:0] IND_NONE (err 0x02); target[11:0] the start word for all four; target[15:12] 0; addr_lo / len as unicast | `docs/SEQ_ISA.md:1609-1616` |
| the codes are the RTL's E_IND / E_CHAN; MOVY's channel field unchanged (no broadcast MOVY) | `docs/SEQ_ISA.md:1618-1620` |
| WINDOW: B17.2's range rule on the one window; the same bank on all four channels | `docs/SEQ_ISA.md:1622-1627` |
| RETIREMENT: every word in every channel's XWIN FIFO (the unicast burst's commit contract) | `docs/SEQ_ISA.md:1629-1633` |
| XPTR: a unicast MOVX writes XPTR 0; a broadcast leaves all four unchanged; visible to the readback and the next AXI-Lite XWIN write | `docs/SEQ_ISA.md:1635-1642` |
| NO RTL INTERLOCK — running ranges per destination; the model gate + the pass's assert are "the validator" of spec §1.3 (plan review m6) | `docs/SEQ_ISA.md:1644-1655` |
| ADMISSION: {R1, R2, R3} ⊆ device caps; SEQ_CAPS 0xFAB1CA07; the R2-not-fail-closed hazard handled by the validator on the broadcast record | `docs/SEQ_ISA.md:1657-1668` |
| FORWARD COMPATIBILITY — fail-closed at today's E_CHAN refusal | `docs/SEQ_ISA.md:1670-1676` |
| COUNTERS: one mover job, mv_op 0; BM_MVWORK (C6) and BM_MOVX count it once | `docs/SEQ_ISA.md:1678-1680` |
| FORM (a); the ISA does not depend on the form | `docs/SEQ_ISA.md:1682-1687` |
| NOT CLAIMED: cost, push rate, back-pressure, timing (SR16 §6) | `docs/SEQ_ISA.md:1689-1692` |

**Cited RTL, all at HEAD, all today's (pre-R3) code:** the MOVX/MVGO channel
refusal `rtl/seq_unit.sv:798-800`; the error-code localparams
`rtl/seq_unit.sv:298-299`; the unicast MOVX's XPTR-to-0 write
`rtl/seq_movers.sv:904-905`; the burst never touching XPTR
`rtl/matvec_chan.sv:112`; the burst's COMMIT CONTRACT
`rtl/matvec_chan.sv:100-110`; the XPTR readback `rtl/matvec_chan.sv:381`; the
AXI-Lite XWIN push at xptr `rtl/matvec_chan.sv:350-353`. No line of the R3 RTL
is cited; B17.3 says it does not exist yet.

## 2. The caps bit — `sw/hwmap.py` VERIFIED, not edited

SEQ_CAP_BITS already carries R3 at bit 2 (`sw/hwmap.py:358-360`), SR2's one
definition. Tied by test: (r3b) hwmap's bit and B17.0's bit-2 row
(`docs/SEQ_ISA.md:1425`) agree; (r3c) hwmap.seq_caps_word of {R1, R2, R3} is
0xFAB1CA07 and seq_caps_set(0xFAB1CA07) is {R1, R2, R3}; (r3d) B17.3's stated
word and admission set equal those. `sw/hwmap.py` and `rtl/` are byte-identical
between the base c5f255d and the B17.3 commit 40429a0
(`evidence/qwen9b/sr/n2305_r3_1_seqisa_hunkhdr.log:7`). No SEQ_VERSIONS row and
no RTL literal change (R3-8 owns the literal).

## 3. TDD — RED then GREEN (a flag, not a copy)

`evidence/qwen9b/sr/sr2_isa_tdd.py` gains `--r3` (default off). The group runs
after SR2's 39 sub-checks: (r3a) the five encoding rows parse and their err
codes equal the RTL's E_CHAN / E_IND parsed from `rtl/seq_unit.sv`; (r3b) and
(r3c) characterisations of hwmap (they PASS at the base by design — stated in
the docstring); (r3d) doc word and admission set = hwmap; (r3e) the XPTR rule;
(r3f) the running rule per destination, NO RTL INTERLOCK, the same bank, the
fail-closed cite, "the R3 RTL does not exist yet", and the kept status line.
The test and its RED prediction were committed (185c210) before the RED run.

| log | tree | result |
|---|---|---|
| `evidence/qwen9b/sr/n2300_r3_1_isa_tdd_RED.log:67-68` | 185c210 (clean) | **RED**: 45 PASS, 14 FAIL, rc 1; failing r3a r3d r3e r3f — exactly the predicted sub-checks |
| `evidence/qwen9b/sr/n2301_r3_1_isa_tdd_GREEN.log:67-68` | 40429a0 (clean) | **GREEN** with --r3: 59 PASS, 0 FAIL, rc 0 |
| `evidence/qwen9b/sr/n2302_r3_1_isa_tdd_noflag.log:46-47` | 40429a0 (clean) | **without the flag**: 39 PASS, 0 FAIL — SR2's count |
| `evidence/qwen9b/sr/n2303_r3_1_noflag_vs_sr2.log:6` | 40429a0 (clean) | the no-flag run's 39 sub-check lines, header and verdict are IDENTICAL to SR2's committed GREEN (`evidence/qwen9b/sr/n213_sr2fix1_isa_tdd_GREEN.log:47-48`) |
| `evidence/qwen9b/sr/n2306_r3_1_spec_cites_precheck.log:6` | 40429a0 (clean) | spec_cites precheck over `docs/SEQ_ISA.md`: FAIL 0 |

## 4. Cite drift

None. The edit is append-only after the last line (`evidence/qwen9b/sr/n2305_r3_1_seqisa_hunkhdr.log:6`),
so no cite INTO `docs/SEQ_ISA.md` can move, and before the edit nothing in the
tree cited a line past 1579 (a git grep for SEQ_ISA.md:15xx–19xx found cites
only up to line 1579). The o3 drift plan was therefore not run (the brief's
"if SEQ_ISA's lines shift"). `evidence/qwen9b/sr/sr2_isa_tdd.py` grew, but no
document cites it by line (git grep for sr2_isa_tdd.py:N found none).

## 5. Judgment calls

1. **RED prediction's totals were an arithmetic slip.** The docstring predicted
   "45 PASS, 12 FAIL (57)"; the group is 20 sub-checks (7+1+2+2+2+6), not 18, so
   the true prediction was 45 PASS / 14 FAIL (59). Every per-sub-check prediction
   held exactly (n2300); the committed docstring is left as written (not edited
   after the run), and the RED commit message records the slip.
2. **Rows added beyond the brief's list** — MOVX target[15:12] (B17.2's rule),
   addr_lo / len "as unicast", "MOVY's channel field unchanged": each is an
   existing rule restated for the broadcast record, not new semantics.
3. **Counter naming.** The plan's "C6" is the BM1 spec's name for BM_MVWORK;
   B17.3 names the SEQ_ISA registers (BM_MVWORK, BM_MOVX) and gives C6 in
   parentheses, since §B16 has no C-numbers.
4. **FORM.** "The ISA does not depend on the form" is qualified: another form
   would have to meet the same XPTR and retirement rules (a form-(b) replay of
   the unicast path would otherwise write XPTR 0 on its first channel).
5. **Model / pass cites are today's unicast refusals** (`ref/seq_model.py:455`,
   `ref/scripts/reorder_e4.py:225`); B17.3 says the per-destination broadcast
   check lands at R3-3 / R3-5.
6. **Commits made on snoke** with `-c user.name=cah` (the NFS view there is the
   one the runs stamp).

## 6. Does NOT establish

That the validator (R3-2), model (R3-3), pass (R3-5), host (R3-6) or RTL (R3-8)
implements B17.3; that a broadcast costs one MOVX window; any push rate,
back-pressure or timing (`evidence/qwen9b/sr/SR16_R3_DECISION.md:237-252`).
