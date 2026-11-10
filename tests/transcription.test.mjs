import test from "node:test";
import assert from "node:assert/strict";
import { normalizeBasicPitchNotes, resampleForBasicPitch, transcribeWithBasicPitch, BASIC_PITCH_SAMPLE_RATE, PROJECT_MELODY_LIMITS, VOCAL_TARGET_LIMITS } from "../transcription.js";
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

// PERF.3: vocal note targets cover the whole recording; project melody keeps the 60 s / 128-note cap.
const manyEvents=(seconds,every)=>Array.from({length:Math.floor(seconds/every)},(_,i)=>({pitchMidi:60+(i%12),startTimeSeconds:i*every,durationSeconds:every*.8}));
test("project melody limits keep the first 60 s and at most 128 notes",()=>{
  const out=normalizeBasicPitchNotes(manyEvents(180,.25),PROJECT_MELODY_LIMITS);
  assert.equal(out.length,128);
  assert.ok(out.every(n=>n.t+n.d<=60));
});
test("vocal target limits keep notes across a 3-minute recording",()=>{
  const out=normalizeBasicPitchNotes(manyEvents(180,.25),{...VOCAL_TARGET_LIMITS,maxSeconds:180});
  assert.equal(out.length,720);
  assert.equal(out.at(-1).t,179.75);
});
test("vocal target limits clip the last note to the recording length",()=>{
  assert.deepEqual(normalizeBasicPitchNotes([{pitchMidi:60,startTimeSeconds:179.8,durationSeconds:2}],{...VOCAL_TARGET_LIMITS,maxSeconds:180}),[{m:60,t:179.8,d:.2}]);
});

// A stand-in for the Basic Pitch module: it reports one note per second of the recording.
function fakeBasicPitch(calls=[]){
  return async()=>({
    BasicPitch:class{constructor(url){calls.push(url)}async evaluateModel(buffer,onFrames,onProgress){onFrames([[0]],[[0]],[[0]]);onProgress(1)}},
    outputToNotesPoly:()=>calls.duration,
    addPitchBendsToNoteEvents:(_c,raw)=>raw,
    noteFramesToTime:()=>{const every=calls.step||1;return Array.from({length:Math.floor(calls.duration/every)},(_,i)=>({pitchMidi:64,startTimeSeconds:i*every,durationSeconds:every/2}))},
  });
}
const buffer22k=seconds=>({sampleRate:22050,duration:seconds,length:seconds*22050,getChannelData:()=>new Float32Array(1)});
test("transcription refuses recordings over 60 s by default (project melody)",async()=>{
  await assert.rejects(transcribeWithBasicPitch(buffer22k(61),()=>{},{loadModule:fakeBasicPitch()}),/under 60 seconds/);
});
test("vocal target detection accepts a 3-minute recording and returns notes across it",async()=>{
  const calls=[];calls.duration=180;const progress=[];
  const notes=await transcribeWithBasicPitch(buffer22k(180),p=>progress.push(p),{...VOCAL_TARGET_LIMITS,loadModule:fakeBasicPitch(calls)});
  assert.equal(notes.length,180);
  assert.equal(notes.at(-1).t,179);
  assert.deepEqual(progress,[100]);
});
test("project melody transcription (the default) caps notes at 128",async()=>{
  const calls=[];calls.duration=59;calls.step=.25;
  const notes=await transcribeWithBasicPitch(buffer22k(59),()=>{},{loadModule:fakeBasicPitch(calls)});
  assert.equal(notes.length,128);
});
test("vocal target detection clips a note that runs past the end of the recording",async()=>{
  const load=async()=>({
    BasicPitch:class{async evaluateModel(_b,onFrames,onProgress){onFrames([[0]],[[0]],[[0]]);onProgress(1)}},
    outputToNotesPoly:()=>[],addPitchBendsToNoteEvents:(_c,raw)=>raw,
    noteFramesToTime:()=>[{pitchMidi:67,startTimeSeconds:179.5,durationSeconds:3}],
  });
  assert.deepEqual(await transcribeWithBasicPitch(buffer22k(180),()=>{},{...VOCAL_TARGET_LIMITS,loadModule:load}),[{m:67,t:179.5,d:.5}]);
});
