import argparse
import json
import librosa
import numpy as np
import os
import sys

# Mapping from Musical Key to Camelot Wheel Code
# 1A = Ab Minor, 1B = B Major, etc.
KEY_TO_CAMELOT = {
    "Ab minor": "1A", "B major": "1B",
    "Eb minor": "2A", "F# major": "2B",
    "Bb minor": "3A", "Db major": "3B",
    "F minor": "4A", "Ab major": "4B",
    "C minor": "5A", "Eb major": "5B",
    "G minor": "6A", "Bb major": "6B",
    "D minor": "7A", "F major": "7B",
    "A minor": "8A", "C major": "8B",
    "E minor": "9A", "G major": "9B",
    "B minor": "10A", "D major": "10B",
    "F# minor": "11A", "A major": "11B",
    "Db minor": "12A", "E major": "12B",
}

def analyze_track(file_path, output_json):
    print(f"Analyzing {file_path}...")
    
    # Load audio
    y, sr = librosa.load(file_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)
    
    # 1. BPM Analysis
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
    
    # 2. Key Analysis (Simulated via Chroma)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key_idx = np.argmax(np.mean(chroma, axis=1))
    notes = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    # Very basic major/minor decision (this could be improved with a real model, but for now it's medior-level)
    is_minor = np.mean(chroma[3]) > np.mean(chroma[4]) # Primitive check
    key_name = f"{notes[key_idx]} {'minor' if is_minor else 'major'}"
    camelot = KEY_TO_CAMELOT.get(key_name, "Unknown")
    
    # 3. Waveform generation (Downsampled for browser performance)
    num_points = 800
    chunk_size = len(y) // num_points
    waveform = []
    for i in range(num_points):
        chunk = y[i*chunk_size : (i+1)*chunk_size]
        if len(chunk) > 0:
            waveform.append(float(np.max(np.abs(chunk))))
        else:
            waveform.append(0.0)
            
    result = {
        "bpm": round(bpm, 2),
        "key": key_name,
        "camelot": camelot,
        "duration": round(duration, 2),
        "waveform": waveform
    }
    
    with open(output_json, 'w') as f:
        json.dump(result, f)
    
    print("Analysis complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    
    try:
        analyze_track(args.input, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
