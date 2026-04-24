namespace MixerAI.Backend.Models;

public sealed class MixRecommendationPreview
{
    public double OverlayStartSeconds { get; init; }
    public double TransitionCueSeconds { get; init; }
    public double RightStartSeconds { get; init; }
    public string TransitionStyle { get; init; } = string.Empty;
    public double LeftBpm { get; init; }
    public double RightBpm { get; init; }
    public double TempoRatio { get; init; }
    public double ModelProbability { get; init; }
    public double Probability { get; init; }
}
