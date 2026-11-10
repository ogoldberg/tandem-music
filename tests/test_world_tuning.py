import numpy as np
import pytest
from world_tuning import quantize_f0, _target_notes, note_centre

def test_nearest_chromatic_pitch():
    hz=np.array([0.,435.,440.,880.])
    corrected,count=quantize_f0(hz,strength=1.0)
    assert corrected[0]==0
    assert corrected[1]==pytest.approx(440,rel=0.001)
    assert corrected[2]==pytest.approx(440,rel=0.001)
    assert count>=1

def test_no_strength_preserves_original():
    original=np.array([0.,430.,470.])
    result,count=quantize_f0(original,strength=0)
    np.testing.assert_array_equal(result,original)
    assert count==0

def test_scale_selection():
    f0=np.array([440*2**(1/12)])
    result,_=quantize_f0(f0,strength=1.,scale=[0,2,4,5,7,9,11])
    assert result[0]==pytest.approx(440.,rel=.001)

def test_note_editor_targets_override_nearest_semitone():
    f0=np.array([435.,435.,435.,0.])
    times=np.array([0.,.1,.2,.3])
    notes=[{"m":72,"t":0,"d":.3}]
    result,count=_target_notes(f0,times,notes,1.0)
    assert count==3
    # VOX.3: a target the user dragged more than 250 cents away still lands exactly on it,
    # because the whole note moves by its median offset; unvoiced frames stay untouched.
    assert result[:3]==pytest.approx([440*2**(3/12)]*3,rel=1e-9)
    assert result[-1]==0.

def _cents(f0,midi):
    return 1200*np.log2(np.asarray(f0)/(440*2**((midi-69)/12)))

def centre_cents(cents):
    return 100*note_centre(np.asarray(cents)/100)

def _vibrato_note(offset_cents=40.,depth_cents=25.,frames=100):
    times=np.arange(frames)*.01
    cents=offset_cents+depth_cents*np.sin(2*np.pi*5.5*times)
    return 440*2**(cents/1200),times

def test_target_without_vibrato_flattens_the_note():
    f0,times=_vibrato_note()
    out,_=_target_notes(f0,times,[{"m":69,"t":0,"d":1}],1.0)
    assert np.max(np.abs(_cents(out,69)))<1e-6

def test_keep_vibrato_moves_the_note_centre_and_keeps_the_wobble():
    f0,times=_vibrato_note()
    out,count=_target_notes(f0,times,[{"m":69,"t":0,"d":1}],1.0,vibrato=1.0)
    before,after=_cents(f0,69),_cents(out,69)
    assert count==100
    assert abs(centre_cents(after))<1e-6
    # The wobble around the note centre is unchanged.
    assert after-centre_cents(after)==pytest.approx(before-centre_cents(before),abs=1e-6)

def test_partial_vibrato_keeps_that_share_of_the_wobble():
    f0,times=_vibrato_note()
    out,_=_target_notes(f0,times,[{"m":69,"t":0,"d":1}],1.0,vibrato=.5)
    before,after=_cents(f0,69),_cents(out,69)
    assert after-centre_cents(after)==pytest.approx(.5*(before-centre_cents(before)),abs=1e-6)

def test_strength_scales_the_whole_correction_with_vibrato_kept():
    f0,times=_vibrato_note()
    out,_=_target_notes(f0,times,[{"m":69,"t":0,"d":1}],.5,vibrato=1.0)
    assert centre_cents(_cents(out,69))==pytest.approx(.5*centre_cents(_cents(f0,69)),abs=1e-6)

def test_a_stray_octave_frame_is_moved_at_most_250_cents_off_the_note_shift():
    f0=np.full(10,440.);f0[4]=880.
    times=np.arange(10)*.01
    out,_=_target_notes(f0,times,[{"m":69,"t":0,"d":.1}],1.0)
    assert out[4]==pytest.approx(880*2**(-2.5/12))
    assert np.delete(out,4)==pytest.approx(np.full(9,440.))

def test_note_shift_is_limited_to_an_octave():
    f0=np.full(5,440.);times=np.arange(5)*.01
    out,_=_target_notes(f0,times,[{"m":69+20,"t":0,"d":.05}],1.0)
    assert out==pytest.approx(np.full(5,880.))

def test_note_centre_ignores_octave_errors_and_is_the_mean_of_a_vibrato():
    cycle=.25*np.sin(2*np.pi*np.arange(1000)/1000*4.4)
    assert note_centre(cycle)==pytest.approx(np.mean(cycle))
    assert note_centre(np.r_[np.zeros(9),12.])==0.

def test_invalid_vibrato():
    with pytest.raises(ValueError):_target_notes(np.array([440.]),np.array([0.]),[{"m":69,"t":0,"d":.1}],1.,vibrato=1.5)

def test_invalid_strength_and_scale():
    with pytest.raises(ValueError):quantize_f0(np.array([440.]),strength=2)
    with pytest.raises(ValueError):quantize_f0(np.array([440.]),scale=[-1])

def test_world_tune_keeps_timing_across_the_whole_clip():
    # Regression: synthesis used pyworld's default 5 ms frame period while analysis used 10 ms,
    # so the tuned voice played at double speed in the first half and the second half was silent.
    pytest.importorskip("pyworld")
    from world_tuning import world_tune
    sr=16000; t=np.arange(sr*4)/sr
    f=np.where(t<2,440*2**(-35/1200),330*2**(-35/1200))
    ph=2*np.pi*np.cumsum(f)/sr
    x=.3*np.sin(ph)+.15*np.sin(2*ph)
    y,details=world_tune(x,sr,strength=1.)
    assert details["corrected_frames"]>0 and len(y)==len(x)
    rms=lambda s:float(np.sqrt(np.mean(s*s)))
    for second in range(4):
        seg_in,seg_out=x[second*sr:(second+1)*sr],y[second*sr:(second+1)*sr]
        assert rms(seg_out)>.5*rms(seg_in), f"second {second} is near-silent"
    # The pitch change must stay where it was sung: the dominant frequency of each half is unchanged in place.
    def peak_hz(s):
        spec=np.abs(np.fft.rfft(s*np.hanning(len(s))));return np.fft.rfftfreq(len(s),1/sr)[np.argmax(spec)]
    assert abs(peak_hz(y[int(.5*sr):int(1.5*sr)])-440)<6
    assert abs(peak_hz(y[int(2.5*sr):int(3.5*sr)])-329.6)<6

def test_server_still_matches_the_contour_preview_fixture():
    """tests/fixtures/target-correction.json is what contour.js previewCorrection is checked against."""
    import json
    from pathlib import Path
    from tests.fixtures.make_target_correction_fixture import build
    stored=json.loads((Path(__file__).parent/"fixtures"/"target-correction.json").read_text())
    fresh=build()
    for a,b in zip(stored["cases"],fresh["cases"]):
        assert [x is None for x in a["corrected"]]==[x is None for x in b["corrected"]]
        assert [x for x in a["corrected"] if x is not None]==pytest.approx([x for x in b["corrected"] if x is not None],abs=1e-6)
