// The only Basic Pitch exports transcription.js uses, plus TensorFlow.js's getBackend (FIX.1, #18):
// the studio says so when the model runs on the slow pure-JavaScript "cpu" backend (no WebGL);
// and its env (FIX.2): transcription.js turns WebGL packing off, which gives wrong notes on Mali GPUs.
export { BasicPitch, outputToNotesPoly, noteFramesToTime, addPitchBendsToNoteEvents } from "@spotify/basic-pitch";
export { getBackend, env } from "@tensorflow/tfjs";
