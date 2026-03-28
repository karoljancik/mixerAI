using Microsoft.AspNetCore.SignalR;
using Microsoft.AspNetCore.Authorization;

namespace MixerAI.Backend.Hubs;

[Authorize]
public class MixerHub : Hub
{
    // Hub for real-time progress updates and track analysis results
    // Usage: Clients subscribe to updates for their tracks/jobs
    
    public async Task JoinTrackGroup(string trackId)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, $"track_{trackId}");
    }

    public async Task LeaveTrackGroup(string trackId)
    {
        await Groups.RemoveFromGroupAsync(Context.ConnectionId, $"track_{trackId}");
    }
}
