using System.Diagnostics;
using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using Microsoft.EntityFrameworkCore;
using MixerAI.Backend.Data;
using MixerAI.Backend.Entities;
using MixerAI.Backend.Hubs;
using MixerAI.Backend.Infrastructure;

namespace MixerAI.Backend.Services;

public class TrackAnalysisService
{
    private readonly ApplicationDbContext _db;
    private readonly IHubContext<MixerHub> _hubContext;
    private readonly string _pythonExecutable = "python";
    private readonly string _repoRoot;
    private readonly string _uploadPath;

    public TrackAnalysisService(ApplicationDbContext db, IHubContext<MixerHub> hubContext, IHostEnvironment env)
    {
        _db = db;
        _hubContext = hubContext;
        _repoRoot = Path.GetFullPath(Path.Combine(env.ContentRootPath, "..", ".."));
        _uploadPath = Path.Combine(env.ContentRootPath, "App_Data", "UserTracks");
    }

    public async Task ProcessTrackAsync(Guid trackId, CancellationToken cancellationToken)
    {
        var track = await _db.Tracks.FindAsync(new object[] { trackId }, cancellationToken);
        if (track == null) return;

        track.Status = "Analyzing";
        await _db.SaveChangesAsync(cancellationToken);
        
        // Notify SignalR (track group)
        await _hubContext.Clients.Group($"track_{trackId}").SendAsync("TrackUpdate", new { id = trackId, status = "Analyzing" });

        var tempOutput = Path.Combine(Path.GetTempPath(), $"track_anal_{Guid.NewGuid():N}.json");
        var actualFilePath = TrackStoragePathResolver.ResolvePhysicalPath(_uploadPath, track.FilePath);
        
        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = _pythonExecutable,
                ArgumentList = { "ai/analyze_track.py", "--input", actualFilePath, "--output", tempOutput },
                WorkingDirectory = _repoRoot,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using var process = Process.Start(startInfo);
            if (process != null)
            {
                await process.WaitForExitAsync(cancellationToken);
                if (process.ExitCode == 0 && File.Exists(tempOutput))
                {
                    var json = await File.ReadAllTextAsync(tempOutput, cancellationToken);
                    var result = JsonDocument.Parse(json).RootElement;

                    track.BPM = result.GetProperty("bpm").GetDouble();
                    track.CamelotKey = result.GetProperty("camelot").GetString();
                    track.DurationSeconds = result.GetProperty("duration").GetDouble();
                    track.WaveformDataJson = result.GetProperty("waveform").GetRawText();
                    track.Status = "Ready";
                }
                else
                {
                    track.Status = "Error";
                }
            }
        }
        catch
        {
            track.Status = "Error";
        }
        finally
        {
            if (File.Exists(tempOutput)) File.Delete(tempOutput);
        }

        await _db.SaveChangesAsync(cancellationToken);
        await _hubContext.Clients.Group($"track_{trackId}").SendAsync("TrackUpdate", new { 
            id = trackId, 
            status = track.Status,
            bpm = track.BPM,
            key = track.CamelotKey
        });
    }
}
