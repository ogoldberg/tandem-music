// The only Basic Pitch exports transcription.js uses, plus TensorFlow.js's getBackend (FIX.1, #18):
// the studio says so when the model runs on the slow pure-JavaScript "cpu" backend (no WebGL).
export { BasicPitch, outputToNotesPoly, noteFramesToTime, addPitchBendsToNoteEvents } from "@spotify/basic-pitch";
export { getBackend } from "@tensorflow/tfjs";
