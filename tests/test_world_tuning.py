import numpy as np
import pytest
from world_tuning import quantize_f0, _target_notes

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
    # Correction intentionally limited to +/- 250 cents per frame for safe editing.
    assert result[0]>435.
    assert result[-1]==0.

def test_invalid_strength_and_scale():
    with pytest.raises(ValueError):quantize_f0(np.array([440.]),strength=2)
    with pytest.raises(ValueError):quantize_f0(np.array([440.]),scale=[-1])
