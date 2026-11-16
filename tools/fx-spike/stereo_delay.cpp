// FX.0: the MPC Plugin SDK's StereoDelay example (examples/StereoDelay/src/StereoDelay.cpp at
// inmusic-software/mpc-plugin-builder-sdk febd2ca, MIT) without the mpc::Plugin host layer, so the
// same per-block and per-sample code runs as WebAssembly in an AudioWorklet and as a native build.
//
// The signal path is the example's, line for line: in -> [+ feedback] -> delay -> lowcut -> highcut
// -> softclip -> (wet, and back to feedback); out = dry + (wet - dry) * mix. Only the parameter store
// changed: plain floats set through fx_set instead of addParam/get. The SDK's dsp/ headers are used
// unchanged.
//
// C API (one instance per handle; buffers are planar float, `frames` at most the prepared block size):
//   fx_create(sampleRate, maxBlock) -> handle     fx_set(handle, param, value)
//   fx_in(handle, channel) / fx_out(handle, channel) -> float*     fx_process(handle, frames, bpm)
//   fx_reset(handle)     fx_destroy(handle)

#include "dsp/math.h"
#include "dsp/delay_line.h"
#include "dsp/onepole.h"
#include "dsp/smoother.h"
#include "dsp/tempo.h"

#include <vector>

using namespace mpc::dsp;

namespace {

enum Params { kSync, kDivision, kTime, kFeedback, kLowCut, kHighCut, kPingPong, kMix, kNumParams };

class StereoDelay
{
public:
    StereoDelay()
    {
        // The example's defaults: sync on at 1/8, 350 ms free time, 40% feedback, 120 Hz low cut,
        // 6 kHz high cut, ping-pong on, 35% mix.
        p_[kSync] = 1; p_[kDivision] = kDivisionEighth; p_[kTime] = 350.0f; p_[kFeedback] = 40.0f;
        p_[kLowCut] = 120.0f; p_[kHighCut] = 6000.0f; p_[kPingPong] = 1; p_[kMix] = 35.0f;
    }

    void set(int i, float v) { if (i >= 0 && i < kNumParams) p_[i] = v; }

    void prepare(double sampleRate, int maxBlockSize)
    {
        sampleRate_ = sampleRate;
        const int maxSamples = (int)(sampleRate * kMaxDelaySeconds) + 1;
        delayL_.prepare(maxSamples);
        delayR_.prepare(maxSamples);
        time_.setTime(80.0f, sampleRate);
        mix_.setTime(20.0f, sampleRate);
        feedback_.setTime(20.0f, sampleRate);
        for (auto& b : in_) b.assign((size_t)maxBlockSize, 0.0f);
        for (auto& b : out_) b.assign((size_t)maxBlockSize, 0.0f);
        maxBlock_ = maxBlockSize;
    }

    // The example's reset(), which the MPC host calls after prepare(). time_.target() is 0 there,
    // so the first block glides the delay time up from 1 sample, as on the MPC.
    void reset()
    {
        delayL_.reset(); delayR_.reset();
        lowCutL_.reset(); lowCutR_.reset(); highCutL_.reset(); highCutR_.reset();
        time_.snap(time_.target());
        mix_.snap(p_[kMix] * 0.01f);
        feedback_.snap(p_[kFeedback] * 0.01f);
    }

    float* in(int c) { return in_[c & 1].data(); }
    float* out(int c) { return out_[c & 1].data(); }

    void process(int numFrames, double bpm)
    {
        if (numFrames > maxBlock_) numFrames = maxBlock_;
        float ms;
        if ((int)p_[kSync] == 1)
            ms = beatsToSeconds(divisionBeats((int)p_[kDivision]), bpm) * 1000.0f;
        else
            ms = p_[kTime];
        const float maxDelay = (float)delayL_.maxDelay();
        time_.setTarget(clamp(msToSamples(ms, sampleRate_), 1.0f, maxDelay));
        mix_.setTarget(p_[kMix] * 0.01f);
        feedback_.setTarget(p_[kFeedback] * 0.01f);
        lowCutL_.setCutoff(p_[kLowCut], sampleRate_);   lowCutR_.setCutoff(p_[kLowCut], sampleRate_);
        highCutL_.setCutoff(p_[kHighCut], sampleRate_); highCutR_.setCutoff(p_[kHighCut], sampleRate_);
        const bool pingPong = p_[kPingPong] >= 0.5f;

        const float* inL = in_[0].data();
        const float* inR = in_[1].data();
        float* outL = out_[0].data();
        float* outR = out_[1].data();

        for (int i = 0; i < numFrames; ++i)
        {
            const float d = time_.process();
            const float fb = feedback_.process();
            const float mix = mix_.process();
            const float dryL = inL[i], dryR = inR[i];

            float wetL = delayL_.readLinear(d);
            float wetR = delayR_.readLinear(d);

            wetL = softClip(highCutL_.process(lowCutL_.process(wetL)));
            wetR = softClip(highCutR_.process(lowCutR_.process(wetR)));

            if (pingPong)
            {
                const float mono = 0.5f * (dryL + dryR);
                delayL_.write(mono + wetR * fb);
                delayR_.write(wetL * fb);
            }
            else
            {
                delayL_.write(dryL + wetL * fb);
                delayR_.write(dryR + wetR * fb);
            }

            outL[i] = dryL + (wetL - dryL) * mix;
            outR[i] = dryR + (wetR - dryR) * mix;
        }
    }

private:
    static constexpr float kMaxDelaySeconds = 4.0f;

    float p_[kNumParams];
    double sampleRate_ = 44100.0;
    int maxBlock_ = 0;
    std::vector<float> in_[2], out_[2];
    DelayLine delayL_, delayR_;
    OnePoleHP lowCutL_, lowCutR_;
    OnePoleLP highCutL_, highCutR_;
    Smoother time_, mix_, feedback_;
};

} // namespace

extern "C" {

StereoDelay* fx_create(double sampleRate, int maxBlock)
{
    if (sampleRate < 8000.0 || sampleRate > 192000.0 || maxBlock < 1 || maxBlock > 8192) return nullptr;
    StereoDelay* fx = new StereoDelay();
    fx->prepare(sampleRate, maxBlock);
    fx->reset();
    return fx;
}
void fx_set(StereoDelay* fx, int param, float value) { fx->set(param, value); }
void fx_reset(StereoDelay* fx) { fx->reset(); }
float* fx_in(StereoDelay* fx, int channel) { return fx->in(channel); }
float* fx_out(StereoDelay* fx, int channel) { return fx->out(channel); }
void fx_process(StereoDelay* fx, int frames, double bpm) { fx->process(frames, bpm); }
void fx_destroy(StereoDelay* fx) { delete fx; }

}
