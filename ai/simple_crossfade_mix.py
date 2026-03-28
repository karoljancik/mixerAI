"""
Simple crossfade mixer — fallback when no trained model exists.
Uses librosa + soundfile to create a smooth crossfade between two tracks.
"""
import argparse
import sys
import os
import numpy as np
import librosa
import soundfile as sf

def crossfade_mix(track_a_path, track_b_path, output_path,
                  crossfade_duration=8.0, sample_rate=44100):
    print(f"Loading Track A: {track_a_path}")
    ya, _ = librosa.load(track_a_path, sr=sample_rate, mono=False)
    print(f"Loading Track B: {track_b_path}")
    yb, _ = librosa.load(track_b_path, sr=sample_rate, mono=False)

    # Ensure stereo
    if ya.ndim == 1:
        ya = np.stack([ya, ya])
    if yb.ndim == 1:
        yb = np.stack([yb, yb])

    cf_samples = int(crossfade_duration * sample_rate)

    # BPM detection for both tracks
    ya_mono = librosa.to_mono(ya)
    yb_mono = librosa.to_mono(yb)
    bpm_a = float(librosa.beat.beat_track(y=ya_mono, sr=sample_rate)[0].item() if hasattr(librosa.beat.beat_track(y=ya_mono, sr=sample_rate)[0], 'item') else librosa.beat.beat_track(y=ya_mono, sr=sample_rate)[0])
    bpm_b = float(librosa.beat.beat_track(y=yb_mono, sr=sample_rate)[0].item() if hasattr(librosa.beat.beat_track(y=yb_mono, sr=sample_rate)[0], 'item') else librosa.beat.beat_track(y=yb_mono, sr=sample_rate)[0])
    print(f"BPM A: {bpm_a:.1f}, BPM B: {bpm_b:.1f}")

    # Time-stretch B to match A's tempo if they differ by more than 2%
    ratio = bpm_a / max(bpm_b, 1.0)
    if abs(ratio - 1.0) > 0.02 and 0.7 < ratio < 1.4:
        print(f"Time-stretching Track B by {ratio:.3f}x to match BPM...")
        yb = np.stack([
            librosa.effects.time_stretch(yb[0], rate=ratio),
            librosa.effects.time_stretch(yb[1], rate=ratio)
        ])

    # Crossfade: play full A, crossfade into B
    fade_out = np.linspace(1.0, 0.0, cf_samples)
    fade_in  = np.linspace(0.0, 1.0, cf_samples)

    # Start of crossfade = 75% through track A
    xf_start = max(0, ya.shape[1] - cf_samples - int(sample_rate * 4))

    output_len = xf_start + cf_samples + max(0, yb.shape[1] - cf_samples)
    out = np.zeros((2, output_len), dtype=np.float32)

    # Track A (full, before crossfade)
    out[:, :ya.shape[1]] += ya

    # Crossfade zone
    cf_end = xf_start + cf_samples
    seg_a = ya[:, xf_start:min(cf_end, ya.shape[1])]
    seg_len = seg_a.shape[1]
    out[:, xf_start:xf_start+seg_len] *= (1.0 - fade_in[:seg_len])  # fade out A
    out[:, xf_start:xf_start+seg_len] += seg_a * 0  # already in

    # Actually just rebuild: mute A in the xfade zone and add B
    out[:, xf_start:xf_start+seg_len] = ya[:, xf_start:xf_start+seg_len] * fade_out[:seg_len]

    # Track B enters at crossfade start
    b_len = min(yb.shape[1], output_len - xf_start)
    b_cf = min(cf_samples, b_len)
    out[:, xf_start:xf_start+b_cf] += yb[:, :b_cf] * fade_in[:b_cf]
    if b_len > cf_samples:
        out[:, xf_start+cf_samples:xf_start+b_len] += yb[:, cf_samples:b_len]

    # Normalize
    peak = np.max(np.abs(out))
    if peak > 0.95:
        out = out * (0.95 / peak)

    # Write output as WAV first, then convert via ffmpeg to MP3
    wav_path = output_path.replace('.mp3', '_tmp.wav')
    sf.write(wav_path, out.T, sample_rate, subtype='PCM_16')
    print(f"Wrote WAV: {wav_path}")

    # Convert to MP3 using ffmpeg (already installed in Docker)
    ret = os.system(f'ffmpeg -y -i "{wav_path}" -b:a 320k "{output_path}" -loglevel error')
    if ret != 0:
        # Fallback: rename wav to mp3-named file (won't be real mp3 but will play)
        os.rename(wav_path, output_path)
    else:
        os.remove(wav_path)

    print(f"Mix complete: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--track-a",  required=True)
    parser.add_argument("--track-b",  required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--model-path",  required=False, help="Ignored – fallback mixer")
    parser.add_argument("--overlay-start-seconds", type=float, default=None)
    parser.add_argument("--right-start-seconds",   type=float, default=None)
    args = parser.parse_args()

    try:
        crossfade_mix(args.track_a, args.track_b, args.output_path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback; traceback.print_exc(file=sys.stderr)
        sys.exit(1)
