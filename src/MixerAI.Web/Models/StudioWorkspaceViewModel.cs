namespace MixerAI.Web.Models;

public sealed class StudioWorkspaceViewModel
{
    public List<TrackViewModel> Tracks { get; init; } = [];
    public MixStudioViewModel Generation { get; init; } = new();
    public TransitionRecommendationRequestViewModel Recommendation { get; init; } = new();
    public IReadOnlyList<string> AvailableSetIds { get; init; } = [];
    public IReadOnlyList<TransitionRecommendationViewModel> RecommendationResults { get; init; } = [];
    public string? RecommendationErrorMessage { get; init; }
    public string? GenerationErrorMessage { get; init; }

    public int ReadyTrackCount => Tracks.Count(track => string.Equals(track.Status, "Ready", StringComparison.OrdinalIgnoreCase));
    public int FailedTrackCount => Tracks.Count(track => string.Equals(track.Status, "Error", StringComparison.OrdinalIgnoreCase));
    public bool HasReadyLibrary => ReadyTrackCount > 0;
}
