namespace MixerAI.Backend.Models;

public sealed class MixJobRecord
{
    public Guid Id { get; init; }
    public string Title { get; init; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public DateTime CreatedAtUtc { get; init; }
    public string TrackAFileName { get; init; } = string.Empty;
    public string TrackBFileName { get; init; } = string.Empty;
    public string WorkingDirectory { get; init; } = string.Empty;
    public string ManifestPath { get; init; } = string.Empty;
}
