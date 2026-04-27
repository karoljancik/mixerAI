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
    private readonly ILogger<TrackAnalysisService> _logger;
    private readonly string _pythonExecutable = "python";
    private readonly string _repoRoot;
    private readonly string _uploadPath;

    public TrackAnalysisService(
        ApplicationDbContext db,
        IHubContext<MixerHub> hubContext,
        IHostEnvironment env,
        ILogger<TrackAnalysisService> logger)
    {
        _db = db;
        _hubContext = hubContext;
        _logger = logger;
        _repoRoot = Path.GetFullPath(Path.Combine(env.ContentRootPath, "..", ".."));
        _uploadPath = Path.Combine(env.ContentRootPath, "App_Data", "UserTracks");
    }

    public async Task ProcessTrackAsync(Guid trackId, CancellationToken cancellationToken)
    {
        var track = await _db.Tracks.FindAsync(new object[] { trackId }, cancellationToken);
        if (track == null) return;

        track.AnalysisAttempts += 1;
        track.LastAnalysisStartedAtUtc = DateTime.UtcNow;
        track.LastAnalysisCompletedAtUtc = null;
        track.LastAnalysisError = null;
        track.Status = "Analyzing";
        await _db.SaveChangesAsync(cancellationToken);

        _logger.LogInformation(
            "Starting track analysis for track {TrackId} ({Title}) on attempt {Attempt}.",
            track.Id,
            track.Title,
            track.AnalysisAttempts);
        
        // Notify SignalR (track group)
        await _hubContext.Clients.Group($"track_{trackId}").SendAsync("TrackUpdate", new
        {
            id = trackId,
            status = "Analyzing",
            attempts = track.AnalysisAttempts
        });

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
            if (process == null)
            {
                throw new InvalidOperationException("Failed to start track analysis process.");
            }

            using var registration = cancellationToken.Register(() =>
            {
                if (!process.HasExited)
                {
                    try
                    {
                        process.Kill(entireProcessTree: true);
                    }
                    catch
                    {
                    }
                }
            });

            await process.WaitForExitAsync(cancellationToken);
            if (process.ExitCode != 0)
            {
                var processError = await process.StandardError.ReadToEndAsync(cancellationToken);
                if (string.IsNullOrWhiteSpace(processError))
                {
                    processError = await process.StandardOutput.ReadToEndAsync(cancellationToken);
                }

                throw new InvalidOperationException($"Track analysis failed: {SummarizeError(processError)}");
            }

            if (!File.Exists(tempOutput))
            {
                throw new InvalidOperationException("Track analysis did not produce an output file.");
            }

            var json = await File.ReadAllTextAsync(tempOutput, cancellationToken);
            var result = JsonDocument.Parse(json).RootElement;

            track.BPM = result.GetProperty("bpm").GetDouble();
            track.BeatOffset = result.TryGetProperty("beat_offset", out var bo) ? bo.GetDouble() : 0.0;
            track.CamelotKey = result.GetProperty("camelot").GetString();
            track.DurationSeconds = result.GetProperty("duration").GetDouble();
            track.WaveformDataJson = result.GetProperty("waveform").GetRawText();
            track.Status = "Ready";
            track.LastAnalysisCompletedAtUtc = DateTime.UtcNow;

            _logger.LogInformation(
                "Completed track analysis for track {TrackId}. BPM {Bpm}, key {CamelotKey}.",
                track.Id,
                track.BPM,
                track.CamelotKey);
        }
        catch (OperationCanceledException exception) when (cancellationToken.IsCancellationRequested)
        {
            track.Status = "Error";
            track.LastAnalysisCompletedAtUtc = DateTime.UtcNow;
            track.LastAnalysisError = "Track analysis was cancelled before completion.";

            _logger.LogWarning(
                exception,
                "Track analysis for track {TrackId} was cancelled on attempt {Attempt}.",
                track.Id,
                track.AnalysisAttempts);
        }
        catch (Exception exception)
        {
            track.Status = "Error";
            track.LastAnalysisCompletedAtUtc = DateTime.UtcNow;
            track.LastAnalysisError = SummarizeError(exception.Message);

            _logger.LogError(
                exception,
                "Track analysis failed for track {TrackId} on attempt {Attempt}.",
                track.Id,
                track.AnalysisAttempts);
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
            key = track.CamelotKey,
            attempts = track.AnalysisAttempts,
            error = track.LastAnalysisError
        });
    }

    private static string SummarizeError(string? error)
    {
        if (string.IsNullOrWhiteSpace(error))
        {
            return "Unknown analysis error.";
        }

        var normalized = error.Replace("\r", " ").Replace("\n", " ").Trim();
        if (normalized.Length > 280)
        {
            normalized = normalized[..280] + "...";
        }

        return normalized;
    }
}
