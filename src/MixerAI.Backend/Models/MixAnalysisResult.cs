namespace MixerAI.Backend.Models;

public sealed class MixAnalysisResult
{
    public MixRecommendationPreview Recommendation { get; init; } = new();
    public MixTrackPreview TrackA { get; init; } = new();
    public MixTrackPreview TrackB { get; init; } = new();
}
