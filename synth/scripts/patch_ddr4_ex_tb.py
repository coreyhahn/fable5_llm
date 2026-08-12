#!/usr/bin/env python3
"""Patch the generated DDR4 example-design TB for custom-part simulation.

Xilinx generates sim_tb_top.sv with the end-of-test Logging block REPLACED by
an unconditional refusal when the DDR4 IP uses a custom part:

    initial begin : Logging
        $display("SIMULATIONS NOT SUPPORTED FOR CUSTOM PART");
        $finish;
    end

Our custom part (Crucial BLS4G4D240FSB-2400) is a standard-timing DDR4-2400
single-rank x8 UDIMM; the TB's Micron memory model is already configured from
the CSV-derived parameters (prints "Configured as x8 4G"). Only the guard
stops the sim. This script replaces the guard with the standard stock-part
logging body: wait for calibration, run traffic for 500 us, then PASS iff no
data compare error; watchdog-fail if calibration never completes.

Usage: patch_ddr4_ex_tb.py <path/to/sim_tb_top.sv>
"""
import sys

GUARD = '''initial
begin : Logging
    $display("SIMULATIONS NOT SUPPORTED FOR CUSTOM PART");
    $finish;
end'''

REPLACEMENT = '''initial
begin : Logging
    // fable5_llm stage-1 patch (synth/scripts/patch_ddr4_ex_tb.py):
    // standard stock-part end-of-test logic restored for custom part.
    $display("FABLE5_PATCH: custom-part sim guard removed");
    fork
       begin : calibration_done
          wait (c0_init_calib_complete);
          $display("FABLE5: CALIBRATION DONE at %t", $time);
          #500us;
          if (!c0_data_compare_error) begin
            $display("FABLE5: TEST PASSED (calib done, 500us traffic, no compare errors)");
          end else begin
            $display("FABLE5: TEST FAILED: DATA COMPARE ERROR");
          end
          disable calib_not_done;
          $finish;
       end
       begin : calib_not_done
          #4ms;
          $display("FABLE5: TEST FAILED: CALIBRATION DID NOT COMPLETE IN 4MS");
          disable calibration_done;
          $finish;
       end
    join
end'''


def main():
    path = sys.argv[1]
    src = open(path).read()
    if 'FABLE5_PATCH' in src:
        print("already patched")
        return
    if GUARD not in src:
        sys.exit("FATAL: custom-part guard not found in expected form")
    open(path, 'w').write(src.replace(GUARD, REPLACEMENT))
    print(f"patched {path}")


if __name__ == "__main__":
    main()
