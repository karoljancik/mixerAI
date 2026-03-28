param(
    [string]$TrainingDir = "data/training",
    [string]$GenerationClipsDir = "data/generated_clips"
)

$ErrorActionPreference = "Stop"

python ai/generation/train_audio_latent_autoencoder.py `
    --train-split-path "$TrainingDir/generation_splits/train.jsonl" `
    --validation-split-path "$TrainingDir/generation_splits/validation.jsonl" `
    --clips-root $GenerationClipsDir `
    --model-output "$TrainingDir/audio_latent_autoencoder.pt"

python ai/generation/train_latent_sequence_generator.py `
    --train-split-path "$TrainingDir/generation_splits/train.jsonl" `
    --validation-split-path "$TrainingDir/generation_splits/validation.jsonl" `
    --clips-root $GenerationClipsDir `
    --autoencoder-model-path "$TrainingDir/audio_latent_autoencoder.pt" `
    --model-output "$TrainingDir/latent_phrase_generator.pt"
