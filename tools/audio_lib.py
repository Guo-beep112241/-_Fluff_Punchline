#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_lib — 程序化环境音 / 音效 / 混音（不联网，不依赖素材库）

设计原则：
  * 全部用 numpy 合成，48 kHz / 立体声 / 16-bit，直接落 WAV
  * 环境音是"循环底噪"，同一集内复用，按镜头随机取相位，避免每镜一样
  * 音效是短事件，长度 0.2–2.5 秒，带轻微的左右声道差，避免死板
  * 音量统一在 -20 dBFS 附近，最终混音时再按镜头调

用法（被 film_pipeline.py 调用）：
    import audio_lib as A
    A.ambience("dorm", 6.0, seed=1)   -> np.float32 stereo array
    A.sfx("paper_drop", seed=2)       -> np.float32 stereo array
    A.write_wav(path, arr)
"""
import numpy as np
import wave

SR = 48000


# ---------------------------------------------------------------- 基础工具

def _rng(seed):
    return np.random.default_rng(seed)


def _t(dur):
    return np.arange(int(SR * dur)) / SR


def _stereo(mono, width=0.0, seed=0):
    """单声道 → 立体声，轻微去相关，避免完全同相的死板感。"""
    if width <= 0:
        return np.stack([mono, mono], axis=1).astype(np.float32)
    r = _rng(seed)
    d = int(SR * 0.002 * r.random())
    right = np.concatenate([np.zeros(d, dtype=np.float32), mono[: len(mono) - d]]) if d else mono
    return np.stack([mono, width * right + (1 - width) * mono], axis=1).astype(np.float32)


def _lowpass(x, cutoff, order=2):
    """一阶/二阶 IIR 低通（对短音频足够）。"""
    x = np.asarray(x, dtype=np.float64)
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    for _ in range(order - 1):
        acc = 0.0
        for i, v in enumerate(y):
            acc = (1 - a) * v + a * acc
            y[i] = acc
    return y


def _highpass(x, cutoff, order=2):
    return np.asarray(x, dtype=np.float64) - _lowpass(x, cutoff, order)


def _bandpass(x, lo, hi):
    return _highpass(_lowpass(x, hi, 1), lo, 1)


def _noise(n, seed=0, color="white"):
    r = _rng(seed)
    x = r.standard_normal(n)
    if color == "pink":
        # 简易 1/f：对白噪声做多段平滑叠加
        x = 0.6 * _lowpass(x, 900, 1) + 0.4 * x
    return x


def _env(n, attack=0.01, decay=0.2, sustain=0.0, release=0.2):
    a = max(1, int(attack * SR))
    d = max(1, int(decay * SR))
    r = max(1, int(release * SR))
    s = max(0, n - a - d - r)
    env = np.concatenate([
        np.linspace(0, 1, a, endpoint=False),
        np.linspace(1, 0.5, d, endpoint=False) if s > 0 else np.array([]),
        np.full(s, 0.5),
        np.linspace(0.5, 0, r),
    ])[:n] if s > 0 else np.linspace(0, 1, n)
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)))
    return env


def _norm(x, peak_db=-12.0):
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    if m <= 1e-9:
        return x
    return x * (10 ** (peak_db / 20.0) / m)


def _fade(x, fin=0.01, fout=0.05):
    n = len(x)
    a = min(n, int(fin * SR))
    b = min(n, int(fout * SR))
    y = np.array(x, dtype=np.float32, copy=True)
    if a:
        y[:a] *= np.linspace(0, 1, a, dtype=np.float32)
    if b:
        y[n - b:] *= np.linspace(1, 0, b, dtype=np.float32)
    return y


def _loop_crossfade(x, target_dur, xf=0.35):
    """把一段循环铺到 target_dur，段间交叉淡化，听起来不会"打点"。"""
    need = int(target_dur * SR)
    x = np.asarray(x, dtype=np.float32)
    if len(x) >= need:
        return x[:need]
    out = x.copy()
    xf_n = min(len(x) // 3, int(xf * SR))
    while len(out) < need:
        a = out[-xf_n:]
        b = x[:xf_n]
        ramp = np.linspace(0, 1, xf_n, dtype=np.float32)[:, None]
        bridge = (a * (1 - ramp) + b * ramp)
        out = np.concatenate([out[:-xf_n], bridge, x[xf_n:]])
    return out[:need]


# ---------------------------------------------------------------- 环境音预设

def _room_tone(dur, seed, level=0.055):
    n = int(dur * SR)
    x = _noise(n, seed, "pink")
    x = _bandpass(x, 60, 2200)
    return x / (np.max(np.abs(x)) + 1e-9) * level


def _hum(dur, seed, level=0.012):
    t = _t(dur)
    x = 0.6 * np.sin(2 * np.pi * 50 * t) + 0.4 * np.sin(2 * np.pi * 100 * t + 0.7)
    mod = 1 + 0.08 * np.sin(2 * np.pi * 0.13 * t)
    return x * mod * level


def _distant_crowd(dur, seed, level=0.05):
    n = int(dur * SR)
    x = _bandpass(_noise(n, seed, "pink"), 240, 1400)
    mod = _lowpass(np.abs(_noise(n, seed + 1)), 0.9, 1)
    mod = mod / (np.max(np.abs(mod)) + 1e-9)
    return x * (0.55 + 0.45 * mod) / (np.max(np.abs(x)) + 1e-9) * level


def _wind(dur, seed, level=0.05):
    n = int(dur * SR)
    x = _bandpass(_noise(n, seed, "pink"), 120, 900)
    swell = _lowpass(np.abs(_noise(n, seed + 3)), 0.35, 1)
    swell = swell / (np.max(np.abs(swell)) + 1e-9)
    return x * (0.35 + 0.65 * swell) / (np.max(np.abs(x)) + 1e-9) * level


def _birds(dur, seed, level=0.02):
    n = int(dur * SR)
    out = np.zeros(n)
    r = _rng(seed)
    t_cursor = 0.4
    while t_cursor < dur - 0.4:
        f0 = r.uniform(2200, 4200)
        ln = r.uniform(0.05, 0.13)
        i0 = int(t_cursor * SR)
        i1 = min(n, i0 + int(ln * SR))
        tt = np.arange(i1 - i0) / SR
        chirp = np.sin(2 * np.pi * (f0 * tt + r.uniform(-1800, 1800) * tt ** 2)) * np.hanning(len(tt))
        out[i0:i1] += chirp * r.uniform(0.4, 1.0)
        t_cursor += r.uniform(0.35, 1.6)
    return out / (np.max(np.abs(out)) + 1e-9) * level


def _clock(dur, seed, level=0.02):
    n = int(dur * SR)
    out = np.zeros(n)
    for k in range(int(dur)):
        i = int(k * SR)
        ln = int(0.012 * SR)
        if i + ln < n:
            out[i:i + ln] += np.hanning(ln) * (1.0 if k % 2 == 0 else 0.7)
    return out / (np.max(np.abs(out)) + 1e-9) * level


AMBIENCE = {
    "corridor": dict(parts=[("room", 0.05), ("hum", 0.014), ("crowd", 0.020)]),
    "dorm":     dict(parts=[("room", 0.07), ("hum", 0.012), ("crowd", 0.012)]),
    "rehearsal": dict(parts=[("room", 0.06), ("hum", 0.016), ("crowd", 0.006)]),
    "lecture":  dict(parts=[("room", 0.05), ("crowd", 0.055), ("hum", 0.010)]),
    "theatre":  dict(parts=[("room", 0.055), ("crowd", 0.030), ("hum", 0.008)]),
    "home":     dict(parts=[("room", 0.06), ("hum", 0.010), ("clock", 0.014)]),
    "campus":   dict(parts=[("wind", 0.045), ("birds", 0.016), ("crowd", 0.020)]),
    "field":    dict(parts=[("wind", 0.060), ("crowd", 0.014), ("birds", 0.008)]),
    "silence":  dict(parts=[("room", 0.030)]),
}


def ambience(name, dur, seed=0):
    cfg = AMBIENCE.get(name, AMBIENCE["dorm"])
    n = int(dur * SR)
    out = np.zeros(n)
    r = _rng(seed)
    for part, lvl in cfg["parts"]:
        if part == "room":
            out += _room_tone(dur, seed, lvl)
        elif part == "hum":
            out += _hum(dur, seed, lvl)
        elif part == "crowd":
            out += _distant_crowd(dur, seed + 11, lvl)
        elif part == "wind":
            out += _wind(dur, seed + 22, lvl)
        elif part == "birds":
            out += _birds(dur, seed + 33, lvl)
        elif part == "clock":
            out += _clock(dur, seed, lvl)
    # 一点点空间感：左右去相关
    out = out / (np.max(np.abs(out)) + 1e-9) * (0.08 + r.uniform(-0.01, 0.01))
    return _stereo(out.astype(np.float32), width=0.35, seed=seed)


# ---------------------------------------------------------------- 音效

def _click(dur=0.02, seed=0, bright=3000, level=0.5):
    n = int(dur * SR)
    x = _noise(n, seed)
    x = _highpass(x, bright, 1)
    x *= np.exp(-np.linspace(0, 6, n))
    return x / (np.max(np.abs(x)) + 1e-9) * level


def _thud(f0=90, dur=0.12, seed=0, level=0.6):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f0 * t * (1 - 0.4 * t / dur)) * np.exp(-t * 22)
    x += _noise(n, seed) * np.exp(-t * 40) * 0.4
    return x / (np.max(np.abs(x)) + 1e-9) * level


def _metal(freqs, dur=1.2, seed=0, level=0.5):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        x += np.sin(2 * np.pi * f * t + k) * np.exp(-t * (4.5 + k * 1.2))
    x += _noise(n, seed) * np.exp(-t * 30) * 0.3
    return x / (np.max(np.abs(x)) + 1e-9) * level


def sfx(name, seed=0):
    r = _rng(seed)
    if name == "paper_flutter":
        n = int(0.45 * SR)
        x = _bandpass(_noise(n, seed), 1200, 7000) * np.abs(np.sin(2 * np.pi * 9 * np.arange(n) / SR)) ** 2
        x = _fade(x / (np.max(np.abs(x)) + 1e-9) * 0.35)
    elif name == "paper_drop":
        x = _thud(140, 0.10, seed, 0.35) * 0.7
        x = np.concatenate([x, _bandpass(_noise(int(0.12 * SR), seed + 1), 900, 5000) * 0.10])
    elif name == "pen_drop":
        x = np.concatenate([_click(0.012, seed, 5000, 0.6), _metal([1800, 2700, 4100], 0.25, seed, 0.25)])
    elif name == "pen_roll":
        parts = [_click(0.01, seed + k, 4000, 0.35) for k in range(6)]
        gaps = [int(SR * (0.09 + 0.03 * k)) for k in range(5)]
        x = parts[0]
        for p, g in zip(parts[1:], gaps):
            x = np.concatenate([x, np.zeros(g), p])
    elif name == "paw_steps":
        seq = [_thud(120, 0.09, seed + k, 0.45) for k in range(4)]
        x = seq[0]
        for p in seq[1:]:
            x = np.concatenate([x, np.zeros(int(SR * 0.22)), p])
    elif name == "tail_thump":
        seq = [_thud(70, 0.16, seed + k, 0.55) for k in range(3)]
        x = seq[0]
        for p in seq[1:]:
            x = np.concatenate([x, np.zeros(int(SR * 0.30)), p])
    elif name == "phone_buzz":
        n = int(0.55 * SR)
        t = np.arange(n) / SR
        gate = (np.sin(2 * np.pi * 7 * t) > 0).astype(float)
        x = np.sin(2 * np.pi * 190 * t) * gate * 0.35
        x += _noise(n, seed) * gate * 0.06
    elif name == "door_open":
        n = int(0.7 * SR)
        t = np.arange(n) / SR
        creak = np.sin(2 * np.pi * (300 + 220 * t) * t) * np.exp(-t * 3) * 0.25
        creak += _bandpass(_noise(n, seed), 600, 3000) * np.exp(-t * 4) * 0.12
        latch = np.concatenate([np.zeros(int(0.6 * SR)), _click(0.03, seed + 1, 2500, 0.5)])
        x = np.concatenate([creak, np.zeros(max(0, len(latch) - len(creak)))])[:max(len(creak), len(latch))]
        x[:len(latch)] += latch
    elif name == "knock":
        seq = [_thud(180, 0.10, seed + k, 0.5) for k in range(3)]
        x = seq[0]
        for p in seq[1:]:
            x = np.concatenate([x, np.zeros(int(SR * 0.26)), p])
    elif name == "mug_break":
        n = int(0.9 * SR)
        t = np.arange(n) / SR
        burst = _bandpass(_noise(n, seed), 1500, 9000) * np.exp(-t * 9)
        x = burst / (np.max(np.abs(burst)) + 1e-9) * 0.55
        for k in range(9):
            i = int(SR * r.uniform(0.05, 0.75))
            c = _click(0.015, seed + k, 6000, 0.25)
            x[i:i + len(c)] += c[:max(0, n - i)]
    elif name == "mic_clang":
        x = _metal([420, 1130, 2270, 3400, 5100], 1.6, seed, 0.55)
    elif name == "applause":
        n = int(2.4 * SR)
        x = np.zeros(n)
        for k in range(260):
            i = int(SR * r.uniform(0, 2.2))
            c = _click(0.008, seed + k, r.uniform(1200, 5000), r.uniform(0.1, 0.35))
            x[i:i + len(c)] += c[:max(0, n - i)]
        env = np.ones(n)
        env[:int(0.12 * SR)] = np.linspace(0, 1, int(0.12 * SR))
        env[-int(0.5 * SR):] = np.linspace(1, 0, int(0.5 * SR))
        x *= env
        x = _bandpass(x, 300, 6000)
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.45
    elif name == "laughter":
        n = int(2.2 * SR)
        x = np.zeros(n)
        for k in range(9):
            i = int(SR * r.uniform(0.05, 1.4))
            ln = int(SR * 0.18)
            tt = np.arange(ln) / SR
            f = r.uniform(180, 320)
            v = (np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * 2.2 * f * tt)) * np.hanning(ln)
            v *= r.uniform(0.4, 1.0)
            x[i:i + ln] += v[:max(0, n - i)]
        x += _bandpass(_noise(n, seed), 400, 2500) * 0.25
        x = _bandpass(x, 200, 3500)
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.4
    elif name == "chair_scrape":
        n = int(0.5 * SR)
        t = np.arange(n) / SR
        x = _bandpass(_noise(n, seed), 600, 3500) * (np.exp(-t * 6)) * (1 + 0.3 * np.sin(2 * np.pi * 24 * t))
    elif name == "sneeze":
        n = int(0.45 * SR)
        t = np.arange(n) / SR
        burst = _bandpass(_noise(n, seed), 600, 6000) * np.exp(-((t - 0.12) ** 2) / 0.004)
        x = burst / (np.max(np.abs(burst)) + 1e-9) * 0.6
    elif name == "breath":
        n = int(1.2 * SR)
        t = np.arange(n) / SR
        env = np.exp(-((t - 0.35) ** 2) / 0.03) + 0.7 * np.exp(-((t - 0.85) ** 2) / 0.04)
        x = _bandpass(_noise(n, seed), 350, 2600) * env
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.3
    elif name == "whine":
        n = int(0.8 * SR)
        t = np.arange(n) / SR
        f = 700 + 500 * (t / 0.8) + 25 * np.sin(2 * np.pi * 6 * t)
        x = np.sin(2 * np.pi * f * t) * np.exp(-t * 2.2) * 0.22
        x += _bandpass(_noise(n, seed), 900, 3000) * np.exp(-t * 3) * 0.05
    elif name == "chalk":
        n = int(0.35 * SR)
        t = np.arange(n) / SR
        x = _bandpass(_noise(n, seed), 1500, 8000) * (0.6 + 0.4 * np.sin(2 * np.pi * 18 * t))
        x *= np.exp(-t * 4)
    elif name == "water_drop":
        n = int(0.25 * SR)
        t = np.arange(n) / SR
        x = np.sin(2 * np.pi * (1200 - 700 * t / 0.25) * t) * np.exp(-t * 18) * 0.4
    elif name == "click":
        x = _click(0.015, seed, 3500, 0.4)
    elif name == "notification":
        n = int(0.7 * SR)
        t = np.arange(n) / SR
        x = np.zeros(n)
        for i, (f, st) in enumerate([(880, 0.0), (1320, 0.14)]):
            i0 = int(st * SR)
            seg = np.sin(2 * np.pi * f * t[:n - i0]) * np.exp(-t[:n - i0] * 9) * 0.3
            x[i0:] += seg
    else:
        x = _thud(120, 0.1, seed, 0.3)
    x = np.asarray(x, dtype=np.float32)
    return _stereo(_fade(x), width=0.15, seed=seed)


# ---------------------------------------------------------------- 写文件

def write_wav(path, arr):
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 1:
        a = np.stack([a, a], axis=1)
    a = np.clip(a, -1.0, 1.0)
    pcm = (a * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


# ---------------------------------------------------------------- 配乐（程序化）

def _pluck(freq, dur, amp=0.25, bright=0.35, seed=0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    env = np.exp(-t * 5.5)
    x = (np.sin(2 * np.pi * freq * t) + bright * np.sin(2 * np.pi * 2 * freq * t)
         + 0.35 * bright * np.sin(2 * np.pi * 3 * freq * t))
    x *= env
    # 拨弦的起音噪声
    atk = np.zeros(n)
    k = min(n, int(0.006 * SR))
    atk[:k] = _noise(k, seed) * np.linspace(1, 0, k) * 0.18
    return (x + atk) * amp


def _note_hz(name):
    # 以 A4=440 为基准的简易音名表（只用中音区）
    names = {"C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.0, "A3": 220.0,
             "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.0, "A4": 440.0,
             "B4": 493.88, "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99}
    return names.get(name, 440.0)


def bgm(dur, seed=0, mood="light"):
    """程序化配乐：I–V–vi–IV 的拨弦分解 + 轻打击，可无缝循环。

    mood: light（轻快） / warm（温暖） / tense（紧张）
    """
    rng = _rng(seed)
    prog = {
        "light": [["C4", "E4", "G4"], ["G3", "B4", "D5"], ["A3", "C4", "E4"], ["F3", "A3", "C5"]],
        "warm": [["C4", "E4", "G4"], ["A3", "C4", "E4"], ["F3", "A3", "C5"], ["G3", "B4", "D5"]],
        "tense": [["A3", "C4", "E4"], ["F3", "A3", "C5"], ["D3", "F3", "A3"], ["E3", "G3", "B4"]],
    }[mood]
    bpm = {"light": 104, "warm": 86, "tense": 92}[mood]
    beat = 60.0 / bpm
    bars = max(4, int(np.ceil(dur / (beat * 4))) + 1)
    total = int(bars * beat * 4 * SR)
    out = np.zeros(total)

    def add(sig, at, gain=1.0):
        i = int(at * SR)
        j = min(total, i + len(sig))
        if i < total:
            out[i:j] += sig[:j - i] * gain

    for b in range(bars):
        chord = prog[b % len(prog)]
        t0 = b * beat * 4
        # 分解和弦（8 分音符）
        pattern = [0, 1, 2, 1, 0, 2, 1, 2]
        for k, idx in enumerate(pattern):
            f = _note_hz(chord[idx % len(chord)])
            add(_pluck(f, beat * 0.9, 0.16 if mood != "tense" else 0.12,
                       bright=0.3, seed=seed + k), t0 + k * beat * 0.5)
        # 低音
        add(_pluck(_note_hz(chord[0]) / 2, beat * 1.6, 0.14, bright=0.15, seed=seed + b), t0)
        # 轻打击
        if mood != "tense":
            for k in (1, 3):
                add(_click(0.01, seed + k, 6000, 0.09), t0 + k * beat)

    out = _bandpass(out, 60, 9000)
    out = out / (np.max(np.abs(out)) + 1e-9) * 0.5
    return _stereo(out.astype(np.float32), width=0.25, seed=seed)
