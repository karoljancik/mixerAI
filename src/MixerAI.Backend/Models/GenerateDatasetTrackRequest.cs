namespace MixerAI.Backend.Models;

public sealed class GenerateDatasetTrackRequest
{
    public string Style { get; init; } = "liquid";
    public int DurationSeconds { get; init; } = 150;
    public int? Seed { get; init; }
}
