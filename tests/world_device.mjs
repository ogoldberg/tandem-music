// VOX.4: tune one clip with the on-device engine (worldtune.js and the vendored WORLD WebAssembly
// build), for tests/test_vocal_benchmark.py. Reads little-endian float32 samples from argv[2],
// writes the tuned float32 samples to argv[3]; argv[4] is JSON {rate, strength, notes, scale,
// vibrato}. Prints {"corrected": n} on stdout.
import { readFileSync, writeFileSync } from "node:fs";
import { bindWorld, worldTune } from "../worldtune.js";
import createWorld from "../vendor/world-d625e76-1/world.mjs";

const [input, output, json] = process.argv.slice(2);
const { rate, strength, notes = null, scale = null, vibrato = 0 } = JSON.parse(json);
const bytes = readFileSync(input);
const samples = new Float32Array(bytes.buffer, bytes.byteOffset, bytes.length / 4);
const world = bindWorld(await createWorld());
const result = worldTune(world, samples, rate, { strength, notes, scale, vibrato });
writeFileSync(output, Buffer.from(result.samples.buffer));
console.log(JSON.stringify({ corrected: result.corrected }));
