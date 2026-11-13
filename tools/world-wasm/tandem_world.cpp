// VOX.4: the WORLD calls world_tuning.py makes through pyworld 0.3.6, with pyworld's default
// options, as three C functions for the WebAssembly build (worldtune.js bindWorld calls them).
#include <stdlib.h>

#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/dio.h"
#include "world/stonemask.h"
#include "world/synthesis.h"

namespace {
// pyworld's default_f0_floor and default_f0_ceil.
const double kF0Floor = 71.0;
const double kF0Ceil = 800.0;

int FFTSize(int fs) {
  CheapTrickOption option;
  InitializeCheapTrickOption(fs, &option);
  option.f0_floor = kF0Floor;
  return GetFFTSizeForCheapTrick(fs, &option);
}

double **Matrix(int rows, int cols) {
  double **m = static_cast<double **>(calloc(rows, sizeof(double *)));
  if (m == NULL) return NULL;
  for (int i = 0; i < rows; ++i) {
    m[i] = static_cast<double *>(calloc(cols, sizeof(double)));
    if (m[i] == NULL) {
      for (int j = 0; j < i; ++j) free(m[j]);
      free(m);
      return NULL;
    }
  }
  return m;
}

void FreeMatrix(double **m, int rows) {
  if (m == NULL) return;
  for (int i = 0; i < rows; ++i) free(m[i]);
  free(m);
}
}  // namespace

extern "C" {

// Number of F0 frames DIO gives for x_length samples.
int tw_frames(int fs, int x_length, double frame_period) {
  return GetSamplesForDIO(fs, x_length, frame_period);
}

// pyworld.dio(x, fs, frame_period=frame_period) then pyworld.stonemask: frame times in t,
// refined F0 in f0 (both tw_frames long).
void tw_f0(const double *x, int x_length, int fs, double frame_period, double *t, double *f0) {
  DioOption option;
  InitializeDioOption(&option);
  option.f0_floor = kF0Floor;
  option.f0_ceil = kF0Ceil;
  option.channels_in_octave = 2.0;
  option.frame_period = frame_period;
  option.speed = 1;
  option.allowed_range = 0.1;
  int frames = tw_frames(fs, x_length, frame_period);
  double *coarse = static_cast<double *>(calloc(frames, sizeof(double)));
  Dio(x, x_length, fs, &option, t, coarse);
  StoneMask(x, x_length, fs, t, coarse, frames, f0);
  free(coarse);
}

// pyworld.cheaptrick and pyworld.d4c (threshold 0.85) on the sung F0, then pyworld.synthesize
// with the corrected F0 into y (y_length = int(frames * frame_period * fs / 1000)).
// Returns 0, or 1 when memory could not be allocated.
int tw_resynth(const double *x, int x_length, int fs, double frame_period, const double *t,
               const double *f0, const double *corrected, int frames, double *y, int y_length) {
  int fft_size = FFTSize(fs), bins = fft_size / 2 + 1;
  double **spectrogram = Matrix(frames, bins), **aperiodicity = Matrix(frames, bins);
  if (spectrogram == NULL || aperiodicity == NULL) {
    FreeMatrix(spectrogram, frames);
    FreeMatrix(aperiodicity, frames);
    return 1;
  }
  CheapTrickOption cheaptrick;
  InitializeCheapTrickOption(fs, &cheaptrick);
  cheaptrick.q1 = -0.15;
  cheaptrick.f0_floor = kF0Floor;
  cheaptrick.fft_size = fft_size;
  CheapTrick(x, x_length, fs, t, f0, frames, &cheaptrick, spectrogram);
  D4COption d4c;
  InitializeD4COption(&d4c);
  d4c.threshold = 0.85;
  D4C(x, x_length, fs, t, f0, frames, fft_size, &d4c, aperiodicity);
  Synthesis(corrected, frames, spectrogram, aperiodicity, fft_size, frame_period, fs, y_length, y);
  FreeMatrix(spectrogram, frames);
  FreeMatrix(aperiodicity, frames);
  return 0;
}

}  // extern "C"
