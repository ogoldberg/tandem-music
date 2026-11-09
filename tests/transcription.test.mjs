import test from "node:test";
import assert from "node:assert/strict";
import { normalizeBasicPitchNotes } from "../transcription.js";
test("sorts and converts Basic Pitch notes into portable project schema",()=>{
  assert.deepEqual(normalizeBasicPitchNotes([
    {pitchMidi:72,startTimeSeconds:1.25,durationSeconds:.4},
    {pitchMidi:60,startTimeSeconds:0,durationSeconds:.7}
  ]), [{m:60,t:0,d:.7},{m:72,t:1.25,d:.4}]);
});
test("rejects invalid notes and clamps durations to recording length",()=>{
  assert.deepEqual(normalizeBasicPitchNotes([
    {pitchMidi:60,startTimeSeconds:59.8,durationSeconds:2},
    {pitchMidi:100,startTimeSeconds:0,durationSeconds:.5},
    {pitchMidi:63,startTimeSeconds:-2,durationSeconds:.5},
    {pitchMidi:60,startTimeSeconds:2,durationSeconds:0}
  ]),[{m:60,t:59.8,d:.2}]);
});
test("does not mutate provider events",()=>{
  const events=[{pitchMidi:66,startTimeSeconds:.5,durationSeconds:.3}];
  const before=JSON.stringify(events);
  normalizeBasicPitchNotes(events);
  assert.equal(JSON.stringify(events),before);
});
