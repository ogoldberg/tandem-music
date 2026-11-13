import test from "node:test";
import assert from "node:assert/strict";
import { normalizeBasicPitchNotes, resampleForBasicPitch, transcribeWithBasicPitch, detectVocalTargets, BASIC_PITCH_SAMPLE_RATE, PROJECT_MELODY_LIMITS, VOCAL_TARGET_LIMITS } from "../transcription.js";
import { frameTime } from "../contour.js";
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

// A stand-in for the Basic Pitch module whose model hears `pitchAt(t)` (MIDI, NaN when nothing is sung):
// each frame's contour peaks at that pitch and its note activation is high there (TRANS.2 reads both).
function sungModel(seconds,pitchAt,calls=[]){
  const contours=[],frames=[];
  for(let r=0;frameTime(r)<seconds;r++){
    const m=pitchAt(frameTime(r)),c=new Array(264).fill(0),f=new Array(88).fill(0);
    if(Number.isFinite(m)){c[Math.round((m-21)*3+1)]=.9;f[Math.round(m)-21]=.7}
    contours.push(c);frames.push(f);
  }
  return async()=>({
    BasicPitch:class{constructor(url){calls.push(url)}async evaluateModel(buffer,onFrames,onProgress){onFrames(frames,frames.map(()=>new Array(88).fill(0)),contours);onProgress(1)}},
    outputToNotesPoly:()=>[],addPitchBendsToNoteEvents:(_c,raw)=>raw,noteFramesToTime:()=>[],
  });
}
// One sung note per `every` seconds, sung for its first half, alternating between E4 and G4.
const notesEvery=(every,t)=>(t%every)<every/2?[64,67][Math.floor(t/every)%2]:NaN;
const buffer22k=seconds=>({sampleRate:22050,duration:seconds,length:seconds*22050,getChannelData:()=>new Float32Array(1)});
test("transcription refuses recordings over 60 s by default (project melody)",async()=>{
  await assert.rejects(transcribeWithBasicPitch(buffer22k(61),()=>{},{loadModule:sungModel(1,()=>NaN)}),/under 60 seconds/);
});
test("melody transcription with the vocal limits accepts a 3-minute recording and returns notes across it",async()=>{
  const calls=[],progress=[];
  const notes=await transcribeWithBasicPitch(buffer22k(180),p=>progress.push(p),{...VOCAL_TARGET_LIMITS,loadModule:sungModel(180,t=>notesEvery(1,t),calls)});
  assert.equal(notes.length,180);
  assert.ok(Math.abs(notes.at(-1).t-179)<.02);
  assert.deepEqual(notes.slice(0,2).map(n=>n.m),[64,67]);
  assert.deepEqual(progress,[100]);
  assert.equal(calls.length,1);
});
test("project melody transcription (the default) caps notes at 128",async()=>{
  const notes=await transcribeWithBasicPitch(buffer22k(59),()=>{},{loadModule:sungModel(59,t=>notesEvery(.25,t))});
  assert.equal(notes.length,128);
});
test("a note sung to the end of the recording ends with it",async()=>{
  const notes=await transcribeWithBasicPitch(buffer22k(3),()=>{},{loadModule:sungModel(3.5,t=>t>=2.5?67:NaN)});
  assert.equal(notes.length,1);
  assert.equal(notes[0].m,67);
  assert.ok(Math.abs(notes[0].t-2.5)<.02);
  assert.ok(notes[0].t+notes[0].d<=3+1e-9 && notes[0].t+notes[0].d>2.97);
});

test("melody transcription follows the sung line: held notes sustain, slides settle, breaths separate (TRANS.2)",async()=>{
  // C4 held with vibrato and a 120 ms dropout inside it, a 250 ms breath, C4 again, then a 150 ms slide up to E4.
  const pitchAt=t=>t<1.2?(t>=.6&&t<.72?NaN:60+.4*Math.sin(2*Math.PI*5.5*t)):t<1.45?NaN:t<1.95?60:t<2.1?60+4*(t-1.95)/.15:t<2.6?64:NaN;
  const notes=await transcribeWithBasicPitch(buffer22k(2.8),()=>{},{loadModule:sungModel(2.8,pitchAt)});
  assert.deepEqual(notes.map(n=>n.m),[60,60,64]);
  assert.ok(Math.abs(notes[0].t)<.02 && Math.abs(notes[0].d-1.2)<.03,`held through the dropout: ${JSON.stringify(notes[0])}`);
  assert.ok(Math.abs(notes[1].t-1.45)<.02,`the breath separates the repeat: ${JSON.stringify(notes[1])}`);
  assert.ok(notes[2].t<2.03 && Math.abs(notes[2].t+notes[2].d-2.6)<.03,`the slide belongs to E4: ${JSON.stringify(notes[2])}`);
});

test("vocal targets can carry a 0..1 confidence from the note's mean activation; project notes never do",()=>{
  const events=[{pitchMidi:60,startTimeSeconds:0,durationSeconds:.5,amplitude:.734},{pitchMidi:62,startTimeSeconds:.5,durationSeconds:.5,amplitude:1.3},{pitchMidi:64,startTimeSeconds:1,durationSeconds:.5}];
  assert.deepEqual(normalizeBasicPitchNotes(events,{...VOCAL_TARGET_LIMITS,confidence:true}).map(n=>n.c),[.73,1,0]);
  assert.ok(normalizeBasicPitchNotes(events).every(n=>!("c" in n)),"the project schema forbids extra keys");
});
test("detectVocalTargets returns confident notes and the sung pitch contour across the recording",async()=>{
  // Two frames peaking at A4 (MIDI 69, contour bin 145), then a silent frame.
  const peak=Array.from({length:264},(_,b)=>b===145?.9:0),silent=new Array(264).fill(0);
  const load=async()=>({
    BasicPitch:class{async evaluateModel(_b,onFrames,onProgress){onFrames([[0],[0],[0]],[[0],[0],[0]],[peak,peak,silent]);onProgress(1)}},
    outputToNotesPoly:()=>[],addPitchBendsToNoteEvents:(_c,raw)=>raw,
    noteFramesToTime:()=>[{pitchMidi:69,startTimeSeconds:0,durationSeconds:.2,amplitude:.5}],
  });
  const {notes,contour}=await detectVocalTargets(buffer22k(180),()=>{},{loadModule:load});
  assert.deepEqual(notes,[{m:69,t:0,d:.2,c:.5}]);
  assert.equal(contour.m.length,3);
  assert.ok(Math.abs(contour.m[0]-69)<1e-6 && Math.abs(contour.m[1]-69)<1e-6);
  assert.ok(Number.isNaN(contour.m[2]));
});

test("the page gets a task between the model's windows, so it can draw the progress (REC.1)",async()=>{
  // Like Basic Pitch 1.0.1: evaluateModel reports progress, then awaits evaluateSingleFrame, per window.
  // Each window here resolves at once, so without a task between them nothing else could run until the end.
  const seen=[];let ticks=0;
  const load=async()=>({
    BasicPitch:class{
      async evaluateSingleFrame(){return [[0]]}
      async evaluateModel(_b,onFrames,onProgress){
        for(let i=0;i<4;i++){onProgress(i/4);seen.push(ticks);await this.evaluateSingleFrame();onFrames([[0]],[[0]],[[0]])}
        onProgress(1);
      }
    },
    outputToNotesPoly:()=>[],addPitchBendsToNoteEvents:(_c,raw)=>raw,noteFramesToTime:()=>[],
  });
  const timer=setInterval(()=>ticks++,0);
  try{await transcribeWithBasicPitch(buffer22k(4),()=>{},{loadModule:load})}finally{clearInterval(timer)}
  assert.ok(seen.at(-1)>seen[0], `timer ticks seen at each window: ${seen}`);
});
