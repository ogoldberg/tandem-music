import io
import wave
import numpy as np
import pytest
from vocal_tuning import estimate_frequency, tune_vocal, shift_pitch
from fastapi.testclient import TestClient
from tandem_backend import app

def test_frequency_detector_on_slightly_flat_a4():
    sr=22050
    t=np.arange(sr)/sr
    x=.25*np.sin(2*np.pi*435*t)
    hz=estimate_frequency(x,sr,midi_hint=69)
    assert hz is not None
    assert abs(hz-435)<8

def test_pitch_correction_keeps_duration():
    sr=22050
    t=np.arange(sr)/sr
    voice=.25*np.sin(2*np.pi*435*t)
    tuned,meta=tune_vocal(voice,sr,[{"m":69,"t":0,"d":1}],strength=1.0)
    assert len(tuned)==len(voice)
    assert np.all(np.isfinite(tuned))
    assert meta["tuned_notes"]>=1

def test_zero_strength_is_identical_to_input():
    sr=16000
    x=np.sin(2*np.pi*330*np.arange(sr)/sr)*.2
    result,meta=tune_vocal(x,sr,[{"m":64,"t":0,"d":1}],strength=0)
    np.testing.assert_array_equal(result,x)
    assert meta["tuned_notes"]==0

def test_silence_is_not_tuned():
    sr=22050
    x=np.zeros(sr)
    result,meta=tune_vocal(x,sr,[{"m":69,"t":0,"d":1}])
    np.testing.assert_array_equal(result,x)
    assert meta["tuned_notes"]==0

def test_invalid_strength_rejected():
    sr=16000
    buf=io.BytesIO()
    with wave.open(buf,"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(sr)
        wav.writeframes(np.zeros(sr,dtype="<i2").tobytes())
    client=TestClient(app)
    result=client.post("/api/tune?strength=2",files={"file":("silence.wav",buf.getvalue(),"audio/wav")})
    assert result.status_code==400
