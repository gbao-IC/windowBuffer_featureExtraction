# Phase 3C numeric contract — count-domain reference v1

Defined before RTL implementation, 2026-10-17. Scope: prepared 347-word frames.
An input word is interpreted as its exact signed16 INTEGER VALUE for independent
arithmetic verification. This is not a waveform quantizer, physical-unit mapping,
resampler, or approval to feed these count-domain features to the trained model.

Order: rms, population variance, absolute peak, zero-crossing rate, peak-to-peak,
crest, half RMS ratio, signed maximum, RR seconds, previous RR seconds, RR ratio,
SIGNED RR difference. Sign is -1/0/+1; adjacent differing signs count once,
including -/0 and 0/+; denominator is 347. Halves are indices 0..172 and 173..346.
RR descriptor fields are unsigned32 ticks at 360 Hz, copied at start. Zero ticks
are accepted by this arithmetic test contract (including zero/zero); the training
dataset builder excludes nonpositive current RR, so these are robustness probes.

All 12 output words: signed96 two's complement, 32 fractional bits (Q64.32 with
sign included). No implicit conversion to the existing signed32 Q12.20 MLP.
Range is [-2^63, 2^63-2^-32]. All uint32 RR inputs and all signed16 frames fit.
Only crest saturates, exactly to [0,15] as specified by training. Unexpected
arithmetic/range errors abort the result, never silently saturate or wrap.

S=sum(x), T=sum(x*x), A/B=sum of squares in the first173/last174 samples.
Required bounds: |S|<=347*32768=11370496 (signed25); T<=347*2^30
(unsigned39); A/B each fit unsigned38; |x|<=32768 must be computed after
sign extension, not negating signed16 minimum in signed16. Peak uses unsigned16;
peak-to-peak uses unsigned17; sign-change count uses unsigned9 (max346).
N*T-S*S is nonnegative, fits unsigned48, and gives variance /(347*347).

RMS calculation: RNE(sqrt(T/347)*2^48), similarly A/173 and B/174. Compute
floor division of T*2^96 by denominator, then integer square root, retaining
BOTH remainders to decide exact nearest-even rounding of the rational root.
If root=r, square-root remainder=s, division remainder=d, denominator=n,
compare 4*(n*s+d) with n*(4*r+1); equality increments only an odd r.
RMS output rounds this internal F48 value to F32 using nearest-even.

Epsilon is represented as the exact rational 1/1,000,000,000, never rounded to
zero in a binary format. Internal roots U,V,W are F48 integers:

```
f_rms        = RNE(U / 2^16)
f_var        = RNE((347*T-S*S)*2^32 / 347^2)
f_peak       = peak * 2^32
f_zc         = RNE(zc_count*2^32 / 347)
f_ptp        = (max-min) * 2^32
f_crest      = min(15*2^32, RNE(peak*10^9*2^80 / (U*10^9+2^48)))
f_half_ratio = RNE(V*10^9*2^32 / (W*10^9+2^48))
f_max        = signed_max * 2^32
f_rr         = RNE(curr_ticks*2^32 / 360)
f_rr_prev    = RNE(prev_ticks*2^32 / 360)
f_rr_ratio   = RNE(curr_ticks*10^9*2^32 / (prev_ticks*10^9+360))
f_rr_diff    = signed_RNE((curr_ticks-prev_ticks)*2^32 / 360)
```

RNE means round to nearest, ties to even. Signed difference rounds magnitude
then restores sign. Division/sqrt use a shared unsigned192 iterative unit;
division has a193-bit trial remainder; sqrt root is96 bits. Largest feature
numerator is below2^135; no 192-bit loss occurs in supported operations.
Largest half ratio is32768*10^9; largest RR ratio is(2^32-1)*10^9/360,
both fit Q64.32. These widths are deliberately conservative, not resource signoff.

The mathematical feature definitions agree with training, but accumulation is
exact integer arithmetic, epsilon is rational, and roots have explicit F48
rounding. Original preprocessing starts from float32 and uses NumPy/SciPy;
bit identity to that pipeline is NOT claimed. Quantized-root versus ideal-real
error is measured separately from RTL versus this bit-exact reference.

Interface: start accepted only when frame_valid and engine ready. Snapshot frame
ID, beat index and both RR values. Read addresses0..346 through one outstanding
ready/valid request; accept response only at expected address and without error.
Keep window ownership until result valid/ready handshake, then release. Hold all
features/metadata stable while output stalls. Abort/window fault/frame-invalid
cancels work/result, pulses done with error and requires caller to flush window
(including any pending read); do not reacquire until a clean empty window has
been observed. Reset must be coordinated with Window to discard stale ownership.
No feature computation uses a fixed response delay in place of the handshake.
