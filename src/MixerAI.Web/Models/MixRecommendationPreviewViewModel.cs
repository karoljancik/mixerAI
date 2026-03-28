namespace MixerAI.Web.Models;

public sealed class MixRecommendationPreviewViewModel
{
    public double OverlayStartSeconds { get; init; }
    public double RightStartSeconds { get; init; }
    public double LeftBpm { get; init; }
    public double RightBpm { get; init; }
    public double TempoRatio { get; init; }
    public double ModelProbability { get; init; }
    public double Probability { get; init; }
}
