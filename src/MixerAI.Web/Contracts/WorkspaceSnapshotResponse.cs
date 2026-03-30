using MixerAI.Web.Models;

namespace MixerAI.Web.Contracts;

public sealed class WorkspaceSnapshotResponse
{
    public string DisplayName { get; init; } = string.Empty;
    public IReadOnlyList<TrackViewModel> Tracks { get; init; } = [];
    public IReadOnlyList<string> AvailableSetIds { get; init; } = [];
    public int ReadyTrackCount { get; init; }
    public int FailedTrackCount { get; init; }
    public bool HasReadyLibrary { get; init; }
}
