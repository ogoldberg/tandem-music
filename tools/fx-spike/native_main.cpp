// FX.0: the native build of stereo_delay.cpp, run the way the AudioWorklet runs it.
//
//   fx-native <in.f32> <out.f32> <bpm> [param=value ...]
//
// in.f32: mono float32 little-endian samples at 44.1 kHz, fed to both inputs. out.f32: the left
// output then the right output, each as long as the input. Blocks of 128 frames (the Web Audio
// render quantum), the parameters set before the first block, as the worklet does. Prints the time
// spent in fx_process per second of audio.

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

struct StereoDelay;
extern "C" {
StereoDelay* fx_create(double, int);
void fx_set(StereoDelay*, int, float);
void fx_reset(StereoDelay*);
float* fx_in(StereoDelay*, int);
float* fx_out(StereoDelay*, int);
void fx_process(StereoDelay*, int, double);
}

int main(int argc, char** argv)
{
    if (argc < 4) { std::fprintf(stderr, "usage: fx-native in.f32 out.f32 bpm [param=value ...]\n"); return 2; }
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) { std::perror(argv[1]); return 1; }
    std::vector<float> x;
    float buf[4096];
    size_t n;
    while ((n = std::fread(buf, sizeof(float), 4096, f)) > 0) x.insert(x.end(), buf, buf + n);
    std::fclose(f);
    const double bpm = std::atof(argv[3]);
    const int block = 128;
    StereoDelay* fx = fx_create(44100.0, block);
    for (int a = 4; a < argc; ++a)
    {
        int p; float v;
        if (std::sscanf(argv[a], "%d=%f", &p, &v) != 2) { std::fprintf(stderr, "bad param %s\n", argv[a]); return 2; }
        fx_set(fx, p, v);
    }
    fx_reset(fx);   // the parameters were set after create: reset snaps mix and feedback to them
    std::vector<float> L(x.size()), R(x.size());
    double spent = 0;
    for (size_t at = 0; at < x.size(); at += block)
    {
        const int frames = (int)((x.size() - at) < (size_t)block ? x.size() - at : block);
        std::memcpy(fx_in(fx, 0), &x[at], sizeof(float) * frames);
        std::memcpy(fx_in(fx, 1), &x[at], sizeof(float) * frames);
        auto t0 = std::chrono::steady_clock::now();
        fx_process(fx, frames, bpm);
        spent += std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        std::memcpy(&L[at], fx_out(fx, 0), sizeof(float) * frames);
        std::memcpy(&R[at], fx_out(fx, 1), sizeof(float) * frames);
    }
    FILE* o = std::fopen(argv[2], "wb");
    if (!o) { std::perror(argv[2]); return 1; }
    std::fwrite(L.data(), sizeof(float), L.size(), o);
    std::fwrite(R.data(), sizeof(float), R.size(), o);
    std::fclose(o);
    std::printf("{\"seconds\": %.6f, \"process_seconds\": %.9f}\n", x.size() / 44100.0, spent);
    return 0;
}
