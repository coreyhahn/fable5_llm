// fx_pkg: shared fixed-point helpers — bit-exact mirrors of ref/fixedpoint.py
// conventions (round-half-away-from-zero everywhere).

`timescale 1ns/1ps

package fx_pkg;

    // round-half-away-from-zero arithmetic right shift (s >= 0)
    function automatic logic signed [63:0] rshr64(input logic signed [63:0] v,
                                                  input int unsigned s);
        logic signed [63:0] mag;
        if (s == 0) return v;
        if (v >= 0) begin
            mag = v + (64'sd1 <<< (s - 1));
            return mag >>> s;
        end else begin
            mag = (-v) + (64'sd1 <<< (s - 1));
            return -(mag >>> s);
        end
    endfunction

    // shift with possibly negative s (negative = left shift)
    function automatic logic signed [63:0] rshr64s(input logic signed [63:0] v,
                                                   input int s);
        if (s >= 0) return rshr64(v, unsigned'(s));
        return v <<< (-s);
    endfunction

    function automatic logic signed [15:0] clip16(input logic signed [63:0] v);
        if (v > 64'sd32767)  return 16'sd32767;
        if (v < -64'sd32768) return -16'sd32768;
        return 16'(v);
    endfunction

endpackage
