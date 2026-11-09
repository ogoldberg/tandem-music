"""Open-source WORLD vocoder pitch correction.

PyWorld provides F0, spectral envelope, and aperiodicity decomposition.
Preserving the spectral envelope while editing F0 approximates formant preservation.
Only isolated monophonic singing is supported.
"""
from __future__ import annotations
import numpy as np
from scipy import signal

def quantize_f0(f0: np.ndarray, *, strength: float = .85, scale: list[int] | None = None):
    """Correct voiced F0 toward the closest allowed MIDI pitch class.

    Unvoiced frames remain zero. Strength 0 leaves F0 unchanged.
    """
    if not 0 <= strength <= 1:
        raise ValueError("Strength must be between 0 and 1")
    if scale is not None:
        if not scale or any(not isinstance(n,int) or n < 0 or n > 11 for n in scale):
            raise ValueError("Scale must contain MIDI pitch classes 0..11")
    f0=np.asarray(f0,dtype=np.float64)
    out=f0.copy()
    voiced=np.isfinite(f0)&(f0>65)&(f0<1100)
    if not np.any(voiced) or strength == 0: return out, 0
    midi=69+12*np.log2(f0[voiced]/440)
    if scale is None:
        target=np.round(midi)
    else:
        allowed=np.array([n for n in range(24,109) if n%12 in scale])
        target=allowed[np.argmin(np.abs(midi[:,None]-allowed[None,:]),axis=1)]
    correction=(target-midi)*strength
    # Limit pitch jumps for incorrect voicing detections; 2 semitones maximum.
    correction=np.clip(correction,-2,2)
    out[voiced]=f0[voiced]*2**(correction/12)
    return out, int(np.count_nonzero(np.abs(correction)>0.02))

def _target_notes(f0, times, notes, strength):
    """Honor manually edited targets within note boundaries instead of scale snapping."""
    out=f0.copy()
    changed=0
    for n in notes[:128]:
        start=float(n["t"]); end=start+float(n["d"]); midi=int(n["m"])
        if midi<36 or midi>96 or start<0 or end<=start:continue
        voiced=(times>=start)&(times<end)&(f0>65)&(f0<1100)&np.isfinite(f0)
        if not np.any(voiced):continue
        target=440*2**((midi-69)/12)
        cents=1200*np.log2(target/f0[voiced])
        cents=np.clip(cents,-250,250)
        out[voiced]=f0[voiced]*2**(strength*cents/1200)
        changed+=int(np.count_nonzero(np.abs(cents*strength)>3))
    return out,changed

FRAME_PERIOD_MS=10.0

def world_tune(samples: np.ndarray, sample_rate: int, strength: float = .85,
               notes: list[dict] | None = None, scale: list[int] | None = None):
    """Return a length-preserving, formant-aware WORLD re-synthesis and metadata."""
    import pyworld as pw
    if not 0<=strength<=1:raise ValueError("Invalid correction strength")
    if sample_rate < 16000:
        raise ValueError("WORLD requires audio sampled at least 16 kHz")
    x=np.asarray(samples,dtype=np.float64)
    if len(x)==0:raise ValueError("Empty recording")
    if strength==0:return x.copy(),{"corrected_frames":0,"engine":"world"}
    # WORLD's time-series analysis remains affordable for short solo vocal clips.
    f0_coarse,t=pw.dio(x,sample_rate,frame_period=FRAME_PERIOD_MS)
    f0=pw.stonemask(x,f0_coarse,t,sample_rate)
    if notes:
        corrected,count=_target_notes(f0,t,notes,strength)
    else:
        corrected,count=quantize_f0(f0,strength=strength,scale=scale)
    if count == 0:return x.copy(),{"corrected_frames":0,"engine":"world"}
    spectral=pw.cheaptrick(x,f0,t,sample_rate)
    aperiodic=pw.d4c(x,f0,t,sample_rate)
    # Synthesis must use the analysis frame period; pyworld defaults to 5 ms and would time-compress.
    y=pw.synthesize(corrected,spectral,aperiodic,sample_rate,frame_period=FRAME_PERIOD_MS)
    if len(y)<len(x):y=np.pad(y,(0,len(x)-len(y)))
    y=y[:len(x)]
    if not np.all(np.isfinite(y)):raise ValueError("WORLD generated non-finite audio")
    # Preserve approximate perceived level, leaving safe headroom.
    before=np.sqrt(np.mean(x*x)+1e-12)
    after=np.sqrt(np.mean(y*y)+1e-12)
    if after>1e-8:y=y*min(4.,before/after)
    return np.clip(y,-.98,.98),{"corrected_frames":count,"engine":"world"}
