# MixerAI Python Service

This folder now contains the first practical training-data scaffolding for long DJ sets with missing track IDs.

## Current scripts

- `service.py`
  Reads a backend mix-job manifest.
- `prepare_dataset.py`
  Builds set manifests and fixed windows from full DJ sets.
- `build_training_pairs.py`
  Generates weakly supervised positive and negative training pairs.
- `extract_features.py`
  Extracts simple per-segment audio features via `ffmpeg`.
- `split_training_pairs.py`
  Splits weakly supervised pairs into train, validation and test files.
- `modeling.py`
  Shared transition model architecture and pair-vector construction.
- `beat_sync.py`
  Deterministic BPM normalization and tempo-alignment helpers for DnB render.
- `train_transition_model.py`
  Trains a deeper `PyTorch` transition scorer with normalization and validation checkpointing.
- `score_transition.py`
  Scores one chosen segment pair with a trained model.
- `recommend_transitions.py`
  Finds the top transition candidates between two sets.
- `evaluate_transition_model.py`
  Evaluates the trained scorer on a labeled split such as `test.jsonl`.
- `summarize_dataset.py`
  Prints a quick summary of manifests, features and training pairs.
- `run_preprocessing.ps1`
  Runs the whole preprocessing pipeline in the right order.

## Recommended first dataset

Use full sets instead of identified tracklists:
- store full audio files under `data/raw_sets/`
- generate manifests under `data/manifests/`
- train on neighboring windows vs distant windows

This is intentionally the lowest-manual-work path.

## Example

```powershell
python ai/prepare_dataset.py --input-dir data/raw_sets --output-dir data/manifests
python ai/build_training_pairs.py --manifests-dir data/manifests --output-path data/training/pairs.jsonl
python ai/split_training_pairs.py --pairs-path data/training/pairs.jsonl --output-dir data/training
python ai/extract_features.py --manifests-dir data/manifests --output-dir data/features
python ai/summarize_dataset.py --manifests-dir data/manifests --features-dir data/features --pairs-path data/training/pairs.jsonl
python ai/train_transition_model.py --pairs-path data/training/train.jsonl --validation-pairs-path data/training/validation.jsonl --features-dir data/features --epochs 40
python ai/evaluate_transition_model.py --pairs-path data/training/test.jsonl --features-dir data/features --model-path data/training/transition_scorer.pt
python ai/recommend_transitions.py --model-path data/training/transition_scorer.pt --features-dir data/features --left-set-id "GLXY & SP_MC @ The Steel Yard, 3rd September 2021 [z9H2bRBEkIQ]" --right-set-id "Nu_Tone _ Let It Roll 2023 [SpH45MfNb48]" --top-k 5
```

When segment timing features change, rebuild both the feature manifests and the generation dataset/clip export.
The generator now depends on beat-entry metadata derived from the raw sets, not only on segment BPM.

## Important limitation

`prepare_dataset.py` now reads `.mp3`, `.wav`, `.flac` and `.aiff` durations via `wave` and `ffprobe`.
If `ffprobe` is missing from the machine, non-`.wav` inputs will fail until it is installed.

The current feature extractor is intentionally simple. The model is now stronger than the feature set, so the next major quality gain will come from better audio features, not just a deeper network.

The render path now separates two responsibilities:
- deterministic beat-sync and tempo alignment
- AI-guided transition selection

That split is important. The model should decide where to transition, while the DSP layer makes the rhythm line up.

## Full-track generation direction

The preset-based generator under `ai/generation/generate_full_track.py` is no longer considered a valid product path.
It does not train a real music generator from the dataset, so it should not be used as evidence that the model can create drum and bass.

The correct direction is:
- build a clip-level corpus from the raw sets
- assign explicit style labels instead of guessing from artist names
- train and evaluate a real generative model offline
- expose inference only after offline quality checks are credible

Keep the source audio in one shared folder such as `data/raw_sets/`.
Do not split raw audio into `deep/` and `liquid/` directories unless that helps you manually browse files.
For training, the authoritative label source should be an explicit map file such as `ai/generation/style_map.curated.json`.
Use `exclude` for sets that are outside the target deep/liquid corpus.

### Generation dataset scripts

- `ai/generation/build_style_dataset.py`
  Builds a small set-level style dataset for exploratory analysis only. Use a curated style map; name inference is now opt-in and `exclude` labels are skipped.
- `ai/generation/prepare_generation_dataset.py`
  Builds a clip-level JSONL manifest from labeled sets and per-segment features. `exclude` sets are skipped.
- `ai/generation/split_generation_dataset.py`
  Splits the clip-level generation dataset into train, validation and test JSONL files by `set_id`, so clips from the same DJ set do not leak across evaluation splits.
- `ai/generation/export_generation_clips.py`
  Cuts concrete mono WAV clips from `generation_dataset*.jsonl` so the next training phase can consume real audio files instead of only metadata.
- `ai/generation/generation_dataset.py`
  PyTorch dataset and collate helpers for loading exported WAV clips from generation splits.
- `ai/generation/inspect_generation_loader.py`
  Runs a batch-level sanity check on the generation clip loader before model training.
- `ai/generation/audio_style_modeling.py`
  Raw-audio style models for liquid-vs-deep classification, including a stronger residual-attention baseline.
- `ai/generation/train_audio_style_baseline.py`
  End-to-end baseline training loop over exported generation clips and clip-level splits.
- `ai/generation/evaluate_audio_style_baseline.py`
  Evaluates the raw-audio baseline on a held-out clip split and prints loss, accuracy and a confusion matrix.
- `ai/generation/phrase_token_codec.py`
  Low-bitrate mu-law tokenization helpers for phrase-level generation experiments.
- `ai/generation/phrase_generator_dataset.py`
  Loads exported clips as short fixed-duration token phrases for autoregressive training.
- `ai/generation/phrase_token_modeling.py`
  Small causal Transformer for style-conditioned phrase token generation.
- `ai/generation/train_phrase_token_generator.py`
  Trains the phrase token generator on exported clips.
- `ai/generation/generate_phrase_track.py`
  Generates a new DnB track by sampling phrase tokens from a trained model. Inference starts from a learned BOS token and prior generated phrases, not from a real prompt clip.
- `ai/generation/audio_latent_modeling.py`
  Convolutional waveform autoencoder that learns a phrase-level latent audio representation.
- `ai/generation/latent_audio_dataset.py`
  Phrase and consecutive-phrase datasets for latent autoencoder and latent sequence training.
- `ai/generation/train_audio_latent_autoencoder.py`
  Trains the phrase-level waveform autoencoder.
- `ai/generation/latent_sequence_modeling.py`
  GRU-based latent phrase generator conditioned on style.
- `ai/generation/train_latent_sequence_generator.py`
  Trains the latent phrase generator on frozen autoencoder latents.
- `ai/generation/generate_latent_track.py`
  Decodes a generated latent phrase sequence back to waveform audio.
- `ai/generation/list_unlabeled_sets.py`
  Prints any set manifests that are still missing from the curated style map. Sets marked as `exclude` are treated as resolved.
- `ai/generation/sample_style_map.json`
  Example style labels. Replace this with a properly curated map before training any real generator.
- `ai/generation/style_map.curated.json`
  Seed explicit labels for the current local set collection.

### Example

```powershell
python ai/generation/list_unlabeled_sets.py --manifests-dir data/manifests --style-map-path ai/generation/style_map.curated.json --output-path data/training/unlabeled_sets.txt
python ai/generation/build_style_dataset.py --features-dir data/features --style-map-path ai/generation/style_map.curated.json --output-path data/training/style_dataset.jsonl
python ai/generation/prepare_generation_dataset.py --manifests-dir data/manifests --features-dir data/features --style-map-path ai/generation/style_map.curated.json --output-path data/training/generation_dataset.curated.jsonl
python ai/generation/split_generation_dataset.py --dataset-path data/training/generation_dataset.curated.jsonl --output-dir data/training/generation_splits
python ai/generation/export_generation_clips.py --dataset-path data/training/generation_dataset.curated.jsonl --output-dir data/generated_clips
python ai/generation/inspect_generation_loader.py --split-path data/training/generation_splits/train.jsonl --clips-root data/generated_clips --batch-size 4
python ai/generation/train_audio_style_baseline.py --train-split-path data/training/generation_splits/train.jsonl --validation-split-path data/training/generation_splits/validation.jsonl --clips-root data/generated_clips --model-type resnet_attn --model-output data/training/audio_style_baseline.pt
python ai/generation/evaluate_audio_style_baseline.py --split-path data/training/generation_splits/test.jsonl --clips-root data/generated_clips --model-path data/training/audio_style_baseline.pt
python ai/generation/train_phrase_token_generator.py --train-split-path data/training/generation_splits/train.jsonl --validation-split-path data/training/generation_splits/validation.jsonl --clips-root data/generated_clips --epochs 12 --model-output data/training/phrase_token_generator.pt
python ai/generation/generate_phrase_track.py --model-path data/training/phrase_token_generator.pt --style liquid --duration-seconds 144 --output-path data/training/generated_phrase_track_liquid.mp3
python ai/generation/train_audio_latent_autoencoder.py --train-split-path data/training/generation_splits/train.jsonl --validation-split-path data/training/generation_splits/validation.jsonl --clips-root data/generated_clips --model-output data/training/audio_latent_autoencoder.pt
python ai/generation/train_latent_sequence_generator.py --train-split-path data/training/generation_splits/train.jsonl --validation-split-path data/training/generation_splits/validation.jsonl --clips-root data/generated_clips --autoencoder-model-path data/training/audio_latent_autoencoder.pt --model-output data/training/latent_phrase_generator.pt
python ai/generation/generate_latent_track.py --autoencoder-model-path data/training/audio_latent_autoencoder.pt --generator-model-path data/training/latent_phrase_generator.pt --style liquid --duration-seconds 96 --output-path data/training/generated_latent_track_liquid.mp3
```

Each output row points to a concrete source file and time range. That keeps the next training phase auditable and lets us later export real clips or build tokenized training batches from these segments.

The clip exporter writes files under style subfolders such as `data/generated_clips/liquid/` and `data/generated_clips/deep/`.
That split is only for exported training clips. Raw source audio can still stay together in `data/raw_sets/`.
