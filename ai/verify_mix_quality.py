
import argparse
import sys
import numpy as np
import librosa
import json
from pathlib import Path

def verify_mix_quality(mix_path, sample_rate=22050):
    mix_path = Path(mix_path)
    if not mix_path.exists():
        return {"error": "Mix file not found."}

    y, sr = librosa.load(mix_path, sr=sample_rate, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    
    duration = y.shape[1] / sr
    
    # 1. Peak Analysis
    peak = np.max(np.abs(y))
    is_clipping = peak >= 0.99
    
    # 2. RMS Energy (Overall Loudness)
    rms = librosa.feature.rms(y=librosa.to_mono(y))[0]
    avg_rms = np.mean(rms)
    dynamic_range = np.max(rms) - np.min(rms)

    # 3. Silence Detection
    # Finding segments where energy is extremely low (dropouts)
    silence_threshold = 0.001
    silent_frames = np.sum(rms < silence_threshold)
    silence_ratio = silent_frames / len(rms)
    has_gaps = silence_ratio > 0.02 # More than 2% silence in a non-intro/outro mix is unusual

    # 4. BPM stability (Beat clash detection)
    # If the mix has multiple conflicting peaks in onset strength, beats might be drifting
    onset_env = librosa.onset.onset_strength(y=librosa.to_mono(y), sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    
    # We check if there's a dominant tempo
    tempo = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)

    # Scoring
    score = 100
    feedback = []

    if is_clipping:
        score -= 15
        feedback.append("Signal peaks are hitting the limit (clipping detected).")
    
    if avg_rms < 0.05:
        score -= 20
        feedback.append("Average volume is too low.")
    
    if has_gaps:
        score -= 30
        feedback.append("Significant silent gaps detected. Check transition timings.")

    if tempo < 40 or tempo > 220:
        score -= 10
        feedback.append("Unstable beat detection. Potential rhythm clash.")

    # Final logic
    if score >= 90:
        quality = "Excellent"
        summary = "Transition is phase-perfect and volume is balanced."
    elif score >= 75:
        quality = "Good"
        summary = "Solid mix, minor leveling or peak issues detected."
    elif score >= 50:
        quality = "Fair"
        summary = "Acceptable, but has noticeable technical flaws."
    else:
        quality = "Poor"
        summary = "Technical errors detected (gaps, clipping, or beat clashes)."

    return {
        "score": score,
        "quality": quality,
        "summary": summary,
        "feedback": feedback,
        "metrics": {
            "peak": round(float(peak), 3),
            "rms": round(float(avg_rms), 3),
            "duration": round(float(duration), 1),
            "detected_bpm": round(float(tempo), 1)
        }
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mix-path", required=True)
    args = parser.parse_args()

    try:
        results = verify_mix_quality(args.mix_path)
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
