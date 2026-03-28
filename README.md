# MixerAI

MixerAI is a prototype for a web application that uploads two drum and bass tracks and creates a mix-processing job.

## Current stack

- `src/MixerAI.Web`: ASP.NET Core MVC frontend
- `src/MixerAI.Backend`: ASP.NET Core backend API
- `ai/`: Python worker boundary for training and inference

## Current behavior

- The web app accepts two audio files and a mix title.
- The backend stores uploaded files under `App_Data/MixJobs/<job-id>`.
- The backend writes a `mix-job.json` manifest for the future Python worker.
- The AI folder contains a first dataset-preparation path for long DJ sets without known track IDs.

## Technical direction

The final AI requirement should be split into phases:

1. Build a reliable upload/job/data pipeline.
2. Add SQL Server for job, dataset and model metadata.
3. Start with deterministic audio preprocessing and alignment.
4. Train or fine-tune a model only after the dataset and evaluation loop are stable.

Full-track generation now prefers the latent-audio generator when `audio_latent_autoencoder.pt` and `latent_phrase_generator.pt` exist. If those checkpoints are missing, inference falls back to the phrase-token/procedural path instead of stitching together dataset clips at render time.

Store raw DJ sets in one directory such as `data/raw_sets`. Keep style labels in metadata, not in the folder layout. Separate `deep` and `liquid` folders are optional for human organization, but the training pipeline should trust an explicit style map file instead of directory names.

When you need style-separated files for training, export derived clips into style subfolders from the labeled manifest instead of physically splitting the original raw set archive.

Mixing two full commercial tracks directly with a "single trained AI model" is not a good first milestone. The right first milestone is an auditable offline pipeline with repeatable inputs and outputs.

For long DJ sets, the lowest-manual-work training path is:

1. Store full sets as raw data.
2. Slice them into fixed windows.
3. Build weakly supervised pairs from adjacent vs distant windows.
4. Train a transition/context scorer before attempting full mix generation.

## Run

Backend:

```powershell
$env:DOTNET_CLI_HOME='c:\Users\Administrator\Desktop\Osobne\mixerAI'
dotnet run --project src/MixerAI.Backend
```

Frontend:

```powershell
$env:DOTNET_CLI_HOME='c:\Users\Administrator\Desktop\Osobne\mixerAI'
dotnet run --project src/MixerAI.Web
```

Python worker example:

```powershell
python ai/service.py --job src/MixerAI.Backend/App_Data/MixJobs/<job-id>/mix-job.json
```

Dataset preparation example:

```powershell
python ai/prepare_dataset.py --input-dir data/raw_sets --output-dir data/manifests
python ai/build_training_pairs.py --manifests-dir data/manifests --output-path data/training/pairs.jsonl
python ai/split_training_pairs.py --pairs-path data/training/pairs.jsonl --output-dir data/training
python ai/extract_features.py --manifests-dir data/manifests --output-dir data/features
python ai/summarize_dataset.py --manifests-dir data/manifests --features-dir data/features --pairs-path data/training/pairs.jsonl
python ai/train_transition_model.py --pairs-path data/training/train.jsonl --validation-pairs-path data/training/validation.jsonl --features-dir data/features --epochs 40
python ai/generation/prepare_generation_dataset.py --manifests-dir data/manifests --features-dir data/features --style-map-path ai/generation/style_map.curated.json --output-path data/training/generation_dataset.curated.jsonl
python ai/generation/export_generation_clips.py --dataset-path data/training/generation_dataset.curated.jsonl --output-dir data/generated_clips
python ai/generation/split_generation_dataset.py --dataset-path data/training/generation_dataset.curated.jsonl --output-dir data/training/generation_splits
python ai/generation/train_phrase_token_generator.py --train-split-path data/training/generation_splits/train.jsonl --validation-split-path data/training/generation_splits/validation.jsonl --clips-root data/generated_clips --model-output data/training/phrase_token_generator.pt
```
