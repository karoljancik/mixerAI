namespace MixerAI.Web.Models;

public sealed class MixAnalysisResultViewModel
{
    public MixRecommendationPreviewViewModel Recommendation { get; init; } = new();
    public MixTrackPreviewViewModel TrackA { get; init; } = new();
    public MixTrackPreviewViewModel TrackB { get; init; } = new();
}
