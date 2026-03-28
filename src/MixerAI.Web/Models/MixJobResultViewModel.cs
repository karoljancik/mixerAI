namespace MixerAI.Web.Models;

public sealed class MixJobResultViewModel
{
    public Guid Id { get; init; }
    public string Title { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    public DateTime CreatedAtUtc { get; init; }
    public string TrackAFileName { get; init; } = string.Empty;
    public string TrackBFileName { get; init; } = string.Empty;
}
