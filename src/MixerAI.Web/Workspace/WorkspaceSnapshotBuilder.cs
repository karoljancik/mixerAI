using System.Security.Claims;
using MixerAI.Web.Contracts;
using MixerAI.Web.Services;

namespace MixerAI.Web.Workspace;

public sealed class WorkspaceSnapshotBuilder
{
    private readonly IMixerBackendClient _backendClient;

    public WorkspaceSnapshotBuilder(IMixerBackendClient backendClient)
    {
        _backendClient = backendClient;
    }

    public async Task<WorkspaceSnapshotResponse> BuildAsync(ClaimsPrincipal user, CancellationToken cancellationToken)
    {
        var tracks = await _backendClient.GetTracksAsync(cancellationToken);
        var setIds = await _backendClient.GetAvailableSetIdsAsync(cancellationToken);
        var displayName = user.Identity?.Name
            ?? user.FindFirst(ClaimTypes.Email)?.Value
            ?? "DJ profile";

        return new WorkspaceSnapshotResponse
        {
            DisplayName = displayName,
            Tracks = tracks,
            AvailableSetIds = setIds,
            ReadyTrackCount = tracks.Count(track => string.Equals(track.Status, "Ready", StringComparison.OrdinalIgnoreCase)),
            FailedTrackCount = tracks.Count(track => string.Equals(track.Status, "Error", StringComparison.OrdinalIgnoreCase)),
            HasReadyLibrary = tracks.Any(track => string.Equals(track.Status, "Ready", StringComparison.OrdinalIgnoreCase))
        };
    }
}
