"""
sfx.py — procedural sound-effect synthesizers for SkySolver.

Every effect is generated from scratch with numpy at runtime (no audio files,
no third-party assets), returning a mono int16 numpy array at SAMPLE_RATE.
Generation is deterministic, so every build produces identical audio.
GENERATORS maps an effect name to its synth function; skysolver.py turns each
returned array into a pygame Sound. All original work.
"""

SAMPLE_RATE = 22050


def rotor_loop(sr=22050):
    import numpy as np

    rng = np.random.RandomState(20260615)

    # ---- Loop geometry: build ONE blade-pass period, tile an integer number of
    # times so the whole buffer is byte-periodic and loops with ZERO click:
    # sample[0] flows out of sample[-1]. A slow ~10.5 Hz blade-pass rate gives
    # the distinct "whop ... whop ... whop" chop (a fast rate blurs together). ----
    n_blades = 7                                    # distinct whops per loop
    target_seconds = 0.667                          # ~10.5 Hz blade-pass rate
    period_len = int(round(sr * target_seconds / n_blades))  # samples / whop
    N = period_len * n_blades                       # exact integer * period
    T = N / sr                                       # true loop length (s)
    t = np.arange(N) / sr                            # no endpoint -> seamless tile
    tp = np.arange(period_len) / sr                  # time within one whop
    frac = np.arange(period_len) / period_len        # 0..1 within one whop

    # ---- Per-whop envelope: fast attack, punchy SHORT decay so each chop is
    # clearly separated by a gap (the whop-whop cadence). Periodic by
    # construction; tiling preserves periodicity. ----
    attack = 0.05
    env1 = np.empty(period_len)
    rise = frac < attack
    env1[rise] = 0.5 - 0.5 * np.cos(np.pi * (frac[rise] / attack))
    dp = (frac[~rise] - attack) / (1.0 - attack)
    env1[~rise] = np.exp(-6.0 * dp) * (0.5 + 0.5 * np.cos(np.pi * dp))
    env = np.tile(env1, n_blades)                    # length N, perfectly periodic

    # integer cycles INSIDE one whop period -> seamless after tiling
    def cyc_period(freq_hz):
        return max(1, int(round(freq_hz * period_len / sr))) * sr / period_len
    # integer cycles over the WHOLE loop -> seamless
    def cyc_loop(freq_hz):
        return max(1, int(round(freq_hz * T))) / T

    # ---- The "whop" body: a low thump plus a higher blade-slap tone, gated by
    # the sharp whump envelope so the chop is punchy. ----
    kernel = (np.sin(2 * np.pi * cyc_period(48.0) * tp)
              + 0.55 * np.sin(2 * np.pi * cyc_period(96.0) * tp)
              + 0.30 * np.sin(2 * np.pi * cyc_period(168.0) * tp)) * env1
    kernel /= (np.max(np.abs(kernel)) + 1e-9)
    thump = np.tile(kernel, n_blades)                # length N, seamless

    # ---- Blade "slap" transient: a short noise burst at each whop onset for the
    # percussive 'wh' attack. Zero at both period ends -> seamless after tiling. ----
    slap_attack = 0.004
    sa = frac < slap_attack
    slap_env1 = np.empty(period_len)
    slap_env1[sa] = 0.5 - 0.5 * np.cos(np.pi * (frac[sa] / slap_attack))
    slap_env1[~sa] = np.exp(-(frac[~sa] - slap_attack) / 0.016)
    slap1 = rng.randn(period_len) * slap_env1
    slap1 /= (np.max(np.abs(slap1)) + 1e-9)
    slap = np.tile(slap1, n_blades)                  # length N, seamless

    # ---- Steady engine drone: low sinusoids, each integer cycles over the loop. ----
    drone = (1.00 * np.sin(2 * np.pi * cyc_loop(84.0) * t)
             + 0.45 * np.sin(2 * np.pi * cyc_loop(168.0) * t + 0.6)
             + 0.20 * np.sin(2 * np.pi * cyc_loop(252.0) * t + 1.3))

    # ---- Broadband "air" noise: periodic, darkened, with a DEEP dip between
    # whops (low floor) so each chop stands out. ----
    noise = np.tile(rng.randn(period_len), n_blades)  # length N, periodic

    def circ_lowpass(x, k):
        c = np.cumsum(np.concatenate([x[-k:], x]))   # circular moving average
        return (c[k:] - c[:-k]) / k
    air = circ_lowpass(circ_lowpass(noise, 16), 8)
    air /= (np.max(np.abs(air)) + 1e-9)
    air = air * (0.08 + 0.92 * env)                  # deep dip between whops

    # ---- Dark/heavy mix; the chops dominate. Gentle circular low-pass keeps
    # it seamless. ----
    out = 1.35 * thump + 0.55 * slap + 0.40 * drone + 0.40 * air
    out = circ_lowpass(out, 4)

    # ---- Anti-clip: normalize peak to 0.7 full scale, then int16. ----
    peak = np.max(np.abs(out)) + 1e-12
    out = np.clip(out / peak * 0.7, -1.0, 1.0)
    return (out * 32767).astype(np.int16)


def thunder(sr=22050):
    import numpy as np
    rng = np.random.RandomState(1337)

    seconds = 1.85
    n = int(sr * seconds)
    t = np.arange(n) / sr

    # shared base noise
    noise = rng.randn(n)

    # ---- CRACK: bright, snappy lightning transient ----
    # differentiate white noise -> emphasize high frequencies (broadband fizz)
    hp = np.diff(noise, prepend=noise[0])
    hp = hp / (np.std(hp) + 1e-9)
    crack_env = np.exp(-t / 0.0045)          # steep decay (main crack)
    snap = np.exp(-t / 0.0008)               # ultra-sharp initial spike
    body_env = np.exp(-t / 0.030)            # slightly longer HF tail (the "rip")
    crack = hp * (crack_env + 1.2 * snap + 0.35 * body_env)
    # short attack ramp so the first sample is not a hard click
    attack_n = max(1, int(sr * 0.0006))
    crack[:attack_n] *= np.linspace(0.0, 1.0, attack_n)

    # ---- RUMBLE: deep low roll with secondary swells ----
    # integrate white noise -> push energy low (red/brown noise)
    red = np.cumsum(noise)
    red = red - red.mean()
    red = red / (np.std(red) + 1e-9)
    # extra low-pass smoothing via box filter for a deeper, less hissy body
    k = np.ones(32) / 32.0
    low = np.convolve(red, k, mode='same')
    low = low / (np.std(low) + 1e-9)

    rumble_env = np.exp(-t / 0.60)           # long exponential decay
    # deterministic slow LFO -> reliable 1-2 swells
    swell = (0.55
             + 0.30 * np.sin(2 * np.pi * 0.9 * t - 0.6)
             + 0.18 * np.sin(2 * np.pi * 1.7 * t + 0.3))
    # a couple of gentle gaussian bumps -> rumble "rolling away in the distance"
    swell = swell + 0.25 * np.exp(-((t - 0.85) ** 2) / (2 * 0.18 ** 2))
    swell = swell + 0.18 * np.exp(-((t - 1.35) ** 2) / (2 * 0.20 ** 2))
    swell = np.clip(swell, 0.0, None)
    onset = 1.0 - np.exp(-t / 0.012)         # bloom in just after the crack
    rumble = low * rumble_env * swell * onset

    # ---- MIX ----
    out = 1.0 * crack + 1.5 * rumble

    # soft saturation: power and glue without harsh digital clipping
    out = np.tanh(out * 1.1)
    out = out - np.mean(out)                  # remove DC so the tail hits true silence

    # ---- click-free fades ----
    fade_in_n = max(1, int(sr * 0.0015))
    fade_out_n = max(1, int(sr * 0.18))
    out[:fade_in_n] *= np.linspace(0.0, 1.0, fade_in_n)
    out[-fade_out_n:] *= np.linspace(1.0, 0.0, fade_out_n) ** 1.5

    # ---- anti-clip normalize to ~0.7 full scale, guard NaN/Inf ----
    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    peak = np.max(np.abs(out))
    if peak < 1e-9:
        peak = 1.0
    out = out / peak * 0.7
    out = (out * 32767.0).astype(np.int16)
    return out


def correct_whoosh(sr=22050):
    import numpy as np
    import math

    seconds = 0.46
    n = int(sr * seconds)
    t = np.arange(n) / float(sr)
    out = np.zeros(n, dtype=np.float64)

    # ---- tiny inline helpers (no per-sample python loops) ----
    def smooth(x, win):
        win = max(1, int(win))
        if win <= 1:
            return x.copy()
        c = np.cumsum(np.insert(x, 0, 0.0))
        sm = (c[win:] - c[:-win]) / win
        pad = np.full(win - 1, sm[0] if sm.size else 0.0)
        return np.concatenate([pad, sm])

    def smoothstep(x):
        x = np.clip(x, 0.0, 1.0)
        return x * x * (3.0 - 2.0 * x)

    # =================================================================
    # 1) RISING WHOOSH -- band-swept filtered noise + faint tonal glide
    #    Genuine low->high band-pass sweep so it reads as a real whoosh.
    # =================================================================
    whoosh_len = int(0.32 * sr)
    wt = t[:whoosh_len]
    wdur = wt[-1] if whoosh_len > 1 else 1.0
    sweep = smoothstep(wt / wdur)              # 0..1 eased

    rng = np.random.RandomState(20240611)
    noise = rng.standard_normal(whoosh_len)

    # exponential rising band-pass centre frequency
    f_start, f_end = 280.0, 4200.0
    fc = f_start * (f_end / f_start) ** sweep

    # fixed log-spaced band-pass layers (narrow-LP minus wider-LP), RMS-normalised
    layer_freqs = np.array([300.0, 600.0, 1100.0, 1900.0, 3000.0, 4200.0])
    layers = np.empty((layer_freqs.size, whoosh_len))
    for i, lf in enumerate(layer_freqs):
        w_narrow = max(2, int(sr / (lf * 1.6)))
        w_wide = max(w_narrow + 2, int(sr / (lf * 0.6)))
        band = smooth(noise, w_narrow) - smooth(noise, w_wide)
        e = np.sqrt(np.mean(band ** 2)) + 1e-9
        layers[i] = band / e

    # log-gaussian crossfade weights that track the rising centre freq
    logf = np.log(layer_freqs)[:, None]
    logfc = np.log(fc)[None, :]
    w = np.exp(-((logf - logfc) ** 2) / (2.0 * 0.45 ** 2))
    w /= (np.sum(w, axis=0, keepdims=True) + 1e-9)
    whoosh_core = np.sum(layers * w, axis=0)

    # faint in-tune tonal glide riding the sweep
    glide = 2.0 * np.pi * np.cumsum(fc) / sr
    whoosh_core = whoosh_core + 0.22 * np.sin(glide)

    # amplitude: soft attack, swell, fade out as the sparkle enters
    env_attack = smoothstep(wt / 0.05)
    env_body = np.exp(-((wt - 0.21) ** 2) / (2.0 * 0.11 ** 2))
    whoosh_env = env_attack * (0.30 + 0.70 * env_body) * (0.30 + 0.70 * sweep)

    whoosh_seg = whoosh_core * whoosh_env
    mx = np.max(np.abs(whoosh_seg))
    if mx > 0:
        whoosh_seg = whoosh_seg / mx
    out[:whoosh_len] += 0.50 * whoosh_seg

    # =================================================================
    # 2) SPARKLE -- ascending bell-like major triad (+octave shimmer)
    #    Clean just-intonation chord => musical, in-tune, cheerful.
    # =================================================================
    root = 880.0  # A5
    # root, M3 (5:4), P5 (3:2), octave, octave+M3  -> just-intonation major
    ratios = [1.0, 5.0 / 4.0, 3.0 / 2.0, 2.0, 5.0 / 2.0]
    onsets = [0.250, 0.268, 0.286, 0.300, 0.320]   # gentle ascending stagger
    amps   = [1.00, 0.85, 0.78, 0.50, 0.34]
    decays = [0.16, 0.15, 0.14, 0.12, 0.095]

    for ratio, onset, amp, dec in zip(ratios, onsets, amps, decays):
        freq = root * ratio
        start = int(onset * sr)
        if start >= n:
            continue
        lt = t[start:] - t[start]
        env = np.exp(-lt / dec) * smoothstep(lt / 0.004)   # ms attack, no click
        partial = np.sin(2.0 * np.pi * freq * lt)
        partial += 0.14 * np.sin(2.0 * np.pi * 2.0 * freq * lt)  # soft shimmer
        out[start:] += amp * 0.30 * partial * env

    # soft POP transient at the hand-off (whoosh -> sparkle)
    pop_start = int(0.250 * sr)
    if pop_start < n:
        pt = t[pop_start:] - t[pop_start]
        pop_env = np.exp(-pt / 0.012)
        pop = np.sin(2.0 * np.pi * (1400.0 * np.exp(-pt / 0.02) + 600.0) * pt)
        out[pop_start:] += 0.13 * pop * pop_env

    # =================================================================
    # 3) de-click fades + gentle de-harsh + anti-clip normalise
    # =================================================================
    fade = max(1, int(0.004 * sr))
    out[:fade] *= np.linspace(0.0, 1.0, fade)
    out[-fade:] *= np.linspace(1.0, 0.0, fade)

    out = 0.85 * out + 0.15 * smooth(out, 2)   # very short smoothing tames harshness

    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.7
    out = np.clip(out, -1.0, 1.0)
    out = (out * 32767.0).astype(np.int16)
    return out


def splash(sr=22050):
    import numpy as np
    rng = np.random.RandomState(1234)

    seconds = 0.72
    n = int(sr * seconds)
    t = np.arange(n) / sr
    out = np.zeros(n, dtype=np.float64)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    # ---- 1) "Sploosh" gush: broadband noise with a FAST downward brightness
    #         sweep, done by crossfading across pre-lowpassed noise bands ----
    spec = np.fft.rfft(rng.randn(n))
    cutoffs = (10000.0, 4500.0, 2000.0, 900.0, 350.0)
    bands = np.stack([np.fft.irfft(spec / (1.0 + (freqs / fc) ** 2), n=n)
                      for fc in cutoffs], axis=0)

    sweep = np.exp(-t / 0.055)                    # 1 -> 0 fast (water displaced)
    bidx = (1.0 - sweep) * (len(cutoffs) - 1)     # bright band -> dark band
    lo = np.floor(bidx).astype(np.intp)
    hi = np.clip(lo + 1, 0, len(cutoffs) - 1)
    frac = bidx - lo
    idx = np.arange(n)
    gush = bands[lo, idx] * (1.0 - frac) + bands[hi, idx] * frac

    # watery amplitude modulation so it is wet, not a dry hiss
    am = (1.0
          + 0.5 * np.sin(2 * np.pi * 23.0 * t + rng.rand() * 6.283)
          + 0.3 * np.sin(2 * np.pi * 47.0 * t + rng.rand() * 6.283))
    am = np.clip(am, 0.0, None)
    gush *= am

    atk = np.clip(t / 0.006, 0, 1)
    burst_env = atk * (0.85 * np.exp(-t / 0.10) + 0.15 * np.exp(-t / 0.32))
    out += gush * burst_env * 1.1

    # low "whump" of displaced water (pitch drops fast)
    whump_f = 130.0 * np.exp(-t / 0.05) + 48.0
    whump = np.sin(2 * np.pi * np.cumsum(whump_f) / sr)
    whump *= np.exp(-t / 0.08) * (1.0 - np.exp(-t / 0.004))
    out += whump * 0.4

    # ---- 2) Bubbly trickle tail: descending-pitch "bloop" bubbles ----
    bub_times = np.array([0.17, 0.26, 0.35, 0.45, 0.55])
    bub_f0    = np.array([900.0, 700.0, 1000.0, 580.0, 760.0])
    bub_amp   = np.array([0.42, 0.36, 0.30, 0.24, 0.18])
    bub_dur   = np.array([0.075, 0.070, 0.065, 0.070, 0.060])
    for i in range(len(bub_times)):
        start = int(bub_times[i] * sr)
        dur_n = min(int(bub_dur[i] * sr), n - start)
        if dur_n <= 1:
            continue
        tb = np.arange(dur_n) / sr
        f_end = bub_f0[i] * 0.5
        finst = f_end + (bub_f0[i] - f_end) * np.exp(-tb / (bub_dur[i] * 0.45))
        phase = 2 * np.pi * np.cumsum(finst) / sr
        benv = (1.0 - np.exp(-tb / 0.004)) * np.exp(-tb / (bub_dur[i] * 0.5))
        out[start:start + dur_n] += np.sin(phase) * benv * bub_amp[i]

    # ---- 3) Fading band-limited noise trickle (wet, not hissy) ----
    spec2 = np.fft.rfft(rng.randn(n))
    Ht = (freqs > 250.0) / (1.0 + (freqs / 1400.0) ** 2)
    trickle = np.fft.irfft(spec2 * Ht, n=n)
    tail_env = np.clip((t - 0.12) / 0.05, 0, 1) * np.exp(-np.clip(t - 0.12, 0, None) / 0.22)
    tam = np.clip(1.0 + 0.6 * np.sin(2 * np.pi * 17.0 * t + rng.rand() * 6.283), 0, None)
    out += trickle * tail_env * tam * 0.26

    # ---- Master decay + click-free fades ----
    out *= 0.55 + 0.45 * np.exp(-t / 0.45)
    fi = max(int(0.003 * sr), 1)
    fo = max(int(0.05 * sr), 1)
    out[:fi] *= np.linspace(0.0, 1.0, fi)
    out[-fo:] *= np.linspace(1.0, 0.0, fo)

    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    peak = np.max(np.abs(out))
    if peak < 1e-9:
        peak = 1.0
    out = out / peak * 0.7
    out = np.clip(out, -1.0, 1.0)
    return (out * 32767.0).astype(np.int16)


def deflate(sr=22050):
    import numpy as np

    seconds = 0.46
    n = int(sr * seconds)
    if n < 2:
        return np.zeros(max(n, 0), dtype=np.int16)
    t = np.arange(n) / float(sr)
    tn = t / t[-1]  # normalized 0..1

    # --- Downward pitch glide that sags and goes "limp" (exponential droop) ---
    f_start = 160.0
    f_end = 64.0
    freq = f_end + (f_start - f_end) * np.exp(-3.0 * tn)
    phase = 2.0 * np.pi * np.cumsum(freq) / float(sr)

    # --- Reedy/buzzy tone: band-limited additive harmonics (no aliasing) ---
    # Roll the harmonics off as pitch drops so the tail stays soft, not harsh.
    harm = [(1, 1.00), (2, 0.55), (3, 0.40), (4, 0.24), (5, 0.15), (6, 0.09)]
    tone = np.zeros(n, dtype=np.float64)
    for k, amp in harm:
        # Gentle high-harmonic damping toward the end for a "going limp" timbre.
        damp = 1.0 - 0.12 * (k - 1) * tn
        tone += amp * np.sin(k * phase) * damp
    tone /= sum(a for _, a in harm)

    # --- Fast amplitude flutter (the raspberry "pbbbbt"), descending in rate ---
    flutter_rate = 32.0 * (1.0 - 0.30 * tn)          # ~32 Hz -> ~22 Hz
    flutter_phase = 2.0 * np.pi * np.cumsum(flutter_rate) / float(sr)
    flutter = 0.5 + 0.5 * (0.7 * np.sin(flutter_phase) + 0.3 * np.sin(2.0 * flutter_phase))
    flutter = 0.38 + 0.62 * flutter                  # depth: dips to ~0.38, never gates fully

    # Slight irregular wobble so the buzz is organic, not a clean tremolo.
    rng = np.random.RandomState(1234)
    noise = rng.standard_normal(n)
    kk = 8
    kern = np.ones(kk) / kk
    noise = np.convolve(noise, kern, mode='same')
    flutter = flutter * (1.0 + 0.10 * noise)
    flutter = np.clip(flutter, 0.0, None)

    body = tone * flutter

    # --- Breathy "spit" noise, gated by flutter, fading fast (light touch) ---
    breath = noise * flutter * np.exp(-5.0 * tn)
    body = body + 0.14 * breath

    # --- Amplitude envelope: quick onset, sagging decay limp to silence ---
    attack_t = 0.010
    a = int(attack_t * sr)
    env = np.ones(n, dtype=np.float64)
    if a > 0:
        env[:a] = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, a))  # raised-cosine attack
    decay = np.exp(-2.8 * tn) * (1.0 - 0.12 * tn)
    env = env * decay
    fo = int(0.06 * sr)
    if fo > 0:
        env[-fo:] *= 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, fo))  # raised-cosine fade-out

    out = body * env

    # --- Anti-clip normalize to ~0.7 full scale, sanitize, convert ---
    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.7
    out = np.clip(out, -1.0, 1.0)
    out = (out * 32767).astype(np.int16)
    return out


GENERATORS = {
    "rotor_loop": rotor_loop,
    "thunder": thunder,
    "correct_whoosh": correct_whoosh,
    "splash": splash,
    "deflate": deflate,
}
