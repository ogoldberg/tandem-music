// FX.0: run delay.wasm in Node exactly as the worklet does (128-frame blocks, mono into both inputs).
//
//   node tools/fx-spike/wasm_node.mjs <delay.wasm> <in.f32> <out.f32> <bpm> [param=value ...]
//
// Writes the left then the right output as float32 and prints the time spent in fx_process.
import { readFileSync, writeFileSync } from "node:fs";

export function runDelay(wasmBytes, mono, bpm, params = []) {
  const { exports: x } = new WebAssembly.Instance(new WebAssembly.Module(wasmBytes), {});
  if (x._initialize) x._initialize();
  const fx = x.fx_create(44100, 128);
  if (!fx) throw new Error("fx_create refused");
  for (const [p, v] of params) x.fx_set(fx, p, v);
  x.fx_reset(fx);
  const heap = new Float32Array(x.memory.buffer);
  const [inL, inR, outL, outR] = [x.fx_in(fx, 0), x.fx_in(fx, 1), x.fx_out(fx, 0), x.fx_out(fx, 1)].map(p => p >> 2);
  const L = new Float32Array(mono.length), R = new Float32Array(mono.length);
  let spent = 0;
  for (let at = 0; at < mono.length; at += 128) {
    const block = mono.subarray(at, Math.min(at + 128, mono.length));
    heap.set(block, inL);
    heap.set(block, inR);
    const t0 = performance.now();
    x.fx_process(fx, block.length, bpm);
    spent += performance.now() - t0;
    L.set(heap.subarray(outL, outL + block.length), at);
    R.set(heap.subarray(outR, outR + block.length), at);
  }
  return { L, R, processSeconds: spent / 1000 };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [wasm, input, output, bpm, ...rest] = process.argv.slice(2);
  const raw = readFileSync(input);
  const mono = new Float32Array(raw.buffer, raw.byteOffset, raw.byteLength / 4);
  const params = rest.map(a => a.split("=").map(Number));
  const { L, R, processSeconds } = runDelay(readFileSync(wasm), mono, Number(bpm), params);
  const out = new Float32Array(L.length * 2);
  out.set(L);
  out.set(R, L.length);
  writeFileSync(output, Buffer.from(out.buffer));
  console.log(JSON.stringify({ seconds: mono.length / 44100, process_seconds: processSeconds }));
}
