# Dataset Plan

This is the first practical dataset strategy for long DJ sets when individual track IDs are missing.

## Goal

Train the first model on set structure and transition likelihood with minimal manual labeling.

## Dataset unit

The base unit is a `set manifest`, not an identified tracklist.

Each set contains:
- source audio file path
- set title
- artist or channel if known
- duration in seconds
- segmentation windows
- transition candidate windows
- optional human notes

## Fastest workflow

1. Import full sets into `data/raw_sets/`.
2. Build a JSON manifest for each set.
3. Slice the set into fixed windows such as `30s`.
4. Mark neighboring windows as positive context pairs.
5. Mark distant windows or windows from other sets as negative pairs.
6. Later add a small reviewed subset with manually confirmed transitions.

## First training target

Do not train a full audio generator first.

Train a model that scores whether two windows belong to a plausible transition context:
- input: window A features + window B features
- output: transition compatibility score

## Weak supervision rules

Positive examples:
- adjacent windows from the same set
- windows around a detected change point

Negative examples:
- windows far apart within the same set
- windows from unrelated sets

## Later improvements

- Add known tracklists when available.
- Add beat grid and phrase detection.
- Add manual review UI for transition candidates.
- Add a sequence model for set ordering after the window scorer is stable.
