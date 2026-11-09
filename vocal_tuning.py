"""Experimental monophonic vocal tuning.

Works best on clean solo voice with held notes. Does not separate vocals from a mix,
edit phonemes, or supply professional-grade formant preservation.
"""
import numpy as np
from scipy import signal

def estimate_frequency(samples: np.ndarray, rate: int, midi_hint: int | None = None):
    """Autocorrelation pitch estimation, constrained by a note hint when present."""
    if len(samples) < int(.075 * rate): return None
    size=min(len(samples),int(.23*rate))
    center=(len(samples)-size)//2
    data=np.asarray(samples[center:center+size],dtype=np.float64)
    data-=np.mean(data)
    rms=np.sqrt(np.mean(data*data))
    if rms<.008:return None
    step=max(1,int(rate/12000))
    data=data[::step]
    sr=rate/step
    data*=np.hanning(len(data))
    cor=signal.fftconvolve(data,data[::-1],mode="full")[len(data)-1:]
    low_hz=75.;high_hz=950.
    if midi_hint is not None:
        target=440*2**((int(midi_hint)-69)/12)
        low_hz=max(75.,target/1.35)
        high_hz=min(950.,target*1.35)
    low=max(1,int(sr/high_hz));high=min(len(cor)-2,int(sr/low_hz))
    if high<=low:return None
    peaks,_=signal.find_peaks(cor[low:high+1])
    if not len(peaks):return None
    ix=low+peaks[np.argmax(cor[low:high+1][peaks])]
    strength=cor[ix]/max(cor[0],1e-12)
    if strength<.23:return None
    # Parabolic interpolation makes correction more precise than integer-lag resolution.
    y0,y1,y2=cor[ix-1:ix+2]
    den=y0-2*y1+y2
    offset=.5*(y0-y2)/den if abs(den)>1e-12 else 0.
    return float(sr/(ix+np.clip(offset,-.5,.5)))

def _phase_vocoder(stft: np.ndarray, rate: float, hop: int, nfft: int):
    """Phase-continuous STFT time scaling, adapted from the standard phase vocoder."""
    steps=np.arange(0,stft.shape[1]-1,rate)
    if len(steps)==0:return stft[:,:1]
    output=np.empty((stft.shape[0],len(steps)),dtype=np.complex128)
    advance=2*np.pi*hop*np.arange(stft.shape[0])/nfft
    phase=np.angle(stft[:,0])
    for i,step in enumerate(steps):
        a=int(step); frac=step-a
        left,right=stft[:,a],stft[:,a+1]
        mag=(1-frac)*np.abs(left)+frac*np.abs(right)
        output[:,i]=mag*np.exp(1j*phase)
        diff=np.angle(right)-np.angle(left)-advance
        diff=(diff+np.pi)%(2*np.pi)-np.pi
        phase+=advance+diff
    return output

def shift_pitch(samples: np.ndarray, rate: int, ratio: float):
    """Change frequency by ratio without changing the sample count."""
    samples=np.asarray(samples,dtype=np.float64)
    if abs(ratio-1)<.001 or len(samples)<512:return samples.copy()
    n=len(samples)
    # Speed up/slower first (pitch change), then restore duration by phase-vocoder.
    shortened=signal.resample(samples,max(512,round(n/ratio)))
    nfft=1024 if rate<=24000 else 2048
    hop=nfft//4
    _,_,stft=signal.stft(shortened,fs=rate,window="hann",nperseg=nfft,
                        noverlap=nfft-hop,boundary="zeros",padded=True)
    outspec=_phase_vocoder(stft,1/ratio,hop,nfft)
    _,out=signal.istft(outspec,fs=rate,window="hann",nperseg=nfft,
                       noverlap=nfft-hop,input_onesided=True,boundary=True)
    if len(out)<n:out=np.pad(out,(0,n-len(out)))
    return out[:n]

def tune_vocal(samples: np.ndarray, rate: int, notes: list, strength: float = 1.,
               max_cents: float = 100.):
    """Tune annotated note regions to their nearest MIDI pitch.

    The note tracker and editor provide note boundaries. Applies correction only
    to stable voiced regions and blends with original around note transitions.
    """
    strength=float(np.clip(strength,0,1))
    x=np.asarray(samples,dtype=np.float64)
    if strength==0 or len(x)==0:return x.copy(),{"tuned_notes":0,"cents":[]}
    output=x.copy()
    corrections=[]
    last_end=0
    for note in sorted(notes,key=lambda n:n["t"])[:128]:
        try:
            midi=int(note["m"]); start=max(last_end,round(float(note["t"])*rate))
            end=min(len(x),round((float(note["t"])+float(note["d"]))*rate))
        except (TypeError,ValueError,KeyError):continue
        if end-start<int(.16*rate) or midi<36 or midi>96:continue
        original=x[start:end]
        detected=estimate_frequency(original,rate,midi_hint=midi)
        if detected is None:continue
        target=440.*2**((midi-69)/12)
        cents=1200*np.log2(target/detected)
        if abs(cents)>max_cents or abs(cents)<3:continue
        ratio=2**(strength*cents/1200)
        processed=shift_pitch(original,rate,ratio)
        if not np.all(np.isfinite(processed)):continue
        # Crossfade the note boundaries to avoid pops and preserve consonants.
        fade=min(round(.045*rate),len(original)//4)
        mix=np.ones(len(original))
        if fade>0:
            mix[:fade]=np.linspace(0,1,fade,endpoint=False)
            mix[-fade:]=np.linspace(1,0,fade)
        output[start:end]=original*(1-mix)+processed*mix
        corrections.append(round(float(strength*cents),1))
        last_end=end
    return output,{"tuned_notes":len(corrections),"cents":corrections}
