namespace MixerAI.Backend.Models;

public sealed class TransitionRecommendationRequest
{
    public string LeftSetId { get; init; } = string.Empty;
    public string RightSetId { get; init; } = string.Empty;
    public int TopK { get; init; } = 5;
    public int MinSegmentIndex { get; init; }
}
