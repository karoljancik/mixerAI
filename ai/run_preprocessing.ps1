param(
    [string]$InputDir = "data/raw_sets",
    [string]$ManifestsDir = "data/manifests",
    [string]$FeaturesDir = "data/features",
    [string]$TrainingDir = "data/training",
    [string]$GenerationClipsDir = "data/generated_clips",
    [string]$StyleMapPath = "ai/generation/style_map.curated.json"
)

$ErrorActionPreference = "Stop"

python ai/prepare_dataset.py --input-dir $InputDir --output-dir $ManifestsDir
python ai/build_training_pairs.py --manifests-dir $ManifestsDir --output-path "$TrainingDir/pairs.jsonl"
python ai/split_training_pairs.py --pairs-path "$TrainingDir/pairs.jsonl" --output-dir $TrainingDir
python ai/extract_features.py --manifests-dir $ManifestsDir --output-dir $FeaturesDir
python ai/summarize_dataset.py --manifests-dir $ManifestsDir --features-dir $FeaturesDir --pairs-path "$TrainingDir/pairs.jsonl"
python ai/generation/prepare_generation_dataset.py --manifests-dir $ManifestsDir --features-dir $FeaturesDir --style-map-path $StyleMapPath --output-path "$TrainingDir/generation_dataset.curated.jsonl"
python ai/generation/export_generation_clips.py --dataset-path "$TrainingDir/generation_dataset.curated.jsonl" --output-dir $GenerationClipsDir
python ai/generation/split_generation_dataset.py --dataset-path "$TrainingDir/generation_dataset.curated.jsonl" --output-dir "$TrainingDir/generation_splits"
python ai/generation/train_phrase_token_generator.py --train-split-path "$TrainingDir/generation_splits/train.jsonl" --validation-split-path "$TrainingDir/generation_splits/validation.jsonl" --clips-root $GenerationClipsDir --model-output "$TrainingDir/phrase_token_generator.pt"
