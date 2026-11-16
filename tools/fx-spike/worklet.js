// FX.0: the StereoDelay port's WebAssembly in an AudioWorklet. The module's bytes come in
// processorOptions (no fetch in the worklet scope); it has no imports, so it is instantiated
// synchronously in the constructor. Every 128-frame quantum: copy the inputs into the module's
// buffers, fx_process, copy its outputs out. A mono input feeds both channels, as the native driver.
// `passthrough` runs the same copies without the module, the baseline for its cost.

class FxDelay extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = options.processorOptions;
    this.bpm = o.bpm;
    this.passthrough = !!o.passthrough;
    if (this.passthrough) return;
    const instance = new WebAssembly.Instance(new WebAssembly.Module(o.wasm), {});
    const x = (this.x = instance.exports);
    if (x._initialize) x._initialize();
    this.fx = x.fx_create(sampleRate, 128);
    if (!this.fx) throw new Error("fx_create refused the sample rate");
    for (const [p, v] of o.params || []) x.fx_set(this.fx, p, v);
    x.fx_reset(this.fx);
    this.heap = new Float32Array(x.memory.buffer);
    this.ptr = [x.fx_in(this.fx, 0), x.fx_in(this.fx, 1), x.fx_out(this.fx, 0), x.fx_out(this.fx, 1)].map(p => p >> 2);
  }

  process(inputs, outputs) {
    const input = inputs[0], output = outputs[0];
    const frames = output[0].length;
    const l = input[0] || new Float32Array(frames), r = input[1] || l;
    if (this.passthrough) {
      output[0].set(l);
      output[1].set(r);
      return true;
    }
    const [inL, inR, outL, outR] = this.ptr;
    this.heap.set(l, inL);
    this.heap.set(r, inR);
    this.x.fx_process(this.fx, frames, this.bpm);
    output[0].set(this.heap.subarray(outL, outL + frames));
    output[1].set(this.heap.subarray(outR, outR + frames));
    return true;
  }
}

registerProcessor("fx-delay", FxDelay);
