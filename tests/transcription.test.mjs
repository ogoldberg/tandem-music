import test from "node:test";
import assert from "node:assert/strict";
import { normalizeBasicPitchNotes, resampleForBasicPitch, BASIC_PITCH_SAMPLE_RATE } from "../transcription.js";
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

test("resamples 48 kHz microphone recordings to Basic Pitch's 22,050 Hz", async ()=>{
  const input = {sampleRate:48000,duration:1, getChannelData:()=>new Float32Array(48000)};
  const calls=[];
  class FakeOfflineContext {
    constructor(channels, length, rate){calls.push([channels,length,rate]);this.destination={};}
    createBufferSource(){return {connect:()=>{},start:()=>{},set buffer(value){calls.push(value.sampleRate)}}}
    async startRendering(){return {sampleRate:22050,duration:1,getChannelData:()=>new Float32Array(22050)}}
  }
  const out=await resampleForBasicPitch(input,FakeOfflineContext);
  assert.equal(out.sampleRate,BASIC_PITCH_SAMPLE_RATE);
  assert.deepEqual(calls,[[1,22050,22050],48000]);
});
test("keeps native 22,050 Hz recordings unchanged",async ()=>{
  const input={sampleRate:22050,duration:1,getChannelData:()=>new Float32Array(22050)};
  assert.strictEqual(await resampleForBasicPitch(input),input);
});
test("rejects an empty input rather than attempting to transcribe",async ()=>{
  const input={sampleRate:48000,duration:0,getChannelData:()=>new Float32Array(0)};
  class FakeOfflineContext {constructor(){}}
  await assert.rejects(resampleForBasicPitch(input,FakeOfflineContext),/empty/);
});
