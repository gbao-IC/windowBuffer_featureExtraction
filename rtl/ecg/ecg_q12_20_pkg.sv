`timescale 1ns/1ps
package ecg_q12_20_pkg;
    // Q12.20 includes sign in the 12 integer bits. All products have F=40.
    // Arithmetic right shift gives floor(), including negative inputs. The
    // low 20 bits are the nonnegative remainder used by Python divmod().
    function automatic logic signed [48:0] round_even_20(input logic signed [67:0] value);
        logic signed [48:0] floor_value;
        logic increment;
        begin
            floor_value = $signed({value[67], value[67:20]});
            increment = value[19] && ((|value[18:0]) || value[20]);
            round_even_20 = floor_value + $signed({48'b0, increment});
        end
    endfunction

    function automatic logic fits_signed32(input logic signed [48:0] value);
        fits_signed32 = (value[48:31] == {18{value[31]}});
    endfunction
endpackage
