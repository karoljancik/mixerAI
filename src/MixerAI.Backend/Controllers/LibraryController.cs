using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using MixerAI.Backend.Data;
using MixerAI.Backend.Entities;
using MixerAI.Backend.Infrastructure;
using MixerAI.Backend.Services;
using System.Security.Claims;

namespace MixerAI.Backend.Controllers;

[Authorize]
[ApiController]
[Route("api/tracks")]
public class LibraryController : ControllerBase
{
    private readonly ApplicationDbContext _db;
    private readonly IBackgroundTaskQueue _taskQueue;
    private readonly string _uploadPath;

    public LibraryController(ApplicationDbContext db, IBackgroundTaskQueue taskQueue, IHostEnvironment env)
    {
        _db = db;
        _taskQueue = taskQueue;
        _uploadPath = Path.Combine(env.ContentRootPath, "App_Data", "UserTracks");
        Directory.CreateDirectory(_uploadPath);
    }

    [HttpGet]
    public async Task<IActionResult> GetTracks()
    {
        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
        var tracks = await _db.Tracks
            .Where(t => t.UserId == userId)
            .OrderByDescending(t => t.CreatedAtUtc)
            .ToListAsync();
        return Ok(tracks);
    }

    [HttpDelete("{id:guid}")]
    public async Task<IActionResult> DeleteTrack(Guid id)
    {
        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
        var track = await _db.Tracks.FirstOrDefaultAsync(t => t.Id == id && t.UserId == userId);
        if (track == null) return NotFound();

        // Reconstruct correct file path using upload path, to ignore absolute paths from previous environment (Windows vs Docker)
        var actualFilePath = TrackStoragePathResolver.ResolvePhysicalPath(_uploadPath, track.FilePath);

        // Delete physical file
        if (System.IO.File.Exists(actualFilePath))
            System.IO.File.Delete(actualFilePath);

        _db.Tracks.Remove(track);
        await _db.SaveChangesAsync();

        return Ok(new { message = "Track deleted." });
    }

    [HttpPost("{id:guid}/retry-analysis")]
    public async Task<IActionResult> RetryTrackAnalysis(Guid id, CancellationToken cancellationToken)
    {
        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
        var track = await _db.Tracks.FirstOrDefaultAsync(t => t.Id == id && t.UserId == userId, cancellationToken);
        if (track == null) return NotFound();
        if (string.Equals(track.Status, "Analyzing", StringComparison.OrdinalIgnoreCase))
        {
            return Conflict(new { error = "Track analysis is already in progress." });
        }

        track.Status = "Pending";
        track.LastAnalysisError = null;
        await _db.SaveChangesAsync(cancellationToken);

        await QueueTrackAnalysisAsync(track.Id);
        return Accepted(new { message = "Track analysis queued.", trackId = track.Id });
    }

    [HttpPost("upload")]
    public async Task<IActionResult> UploadTrack(IFormFile file, CancellationToken cancellationToken)
    {
        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
        if (file == null || file.Length == 0) return BadRequest("File is empty.");

        var trackId = Guid.NewGuid();
        var extension = Path.GetExtension(file.FileName);
        var fileName = $"{trackId:N}{extension}";
        var filePath = Path.Combine(_uploadPath, fileName);

        await using (var stream = new FileStream(filePath, FileMode.Create))
        {
            await file.CopyToAsync(stream);
        }

        var track = new Track
        {
            Id = trackId,
            Title = Path.GetFileNameWithoutExtension(file.FileName),
            FilePath = fileName,
            UserId = userId!,
            Status = "Pending",
            CreatedAtUtc = DateTime.UtcNow
        };

        _db.Tracks.Add(track);
        await _db.SaveChangesAsync(cancellationToken);

        await QueueTrackAnalysisAsync(trackId);

        return Accepted(track);
    }

    [HttpGet("{id:guid}/file")]
    public async Task<IActionResult> GetTrackFile(Guid id)
    {
        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
        var track = await _db.Tracks.FirstOrDefaultAsync(t => t.Id == id && t.UserId == userId);
        if (track == null) return NotFound();

        // Reconstruct correct file path using upload path, to ignore absolute paths from previous environment (Windows vs Docker)
        var actualFilePath = TrackStoragePathResolver.ResolvePhysicalPath(_uploadPath, track.FilePath);

        if (!System.IO.File.Exists(actualFilePath)) return NotFound();

        var ext = Path.GetExtension(actualFilePath).ToLowerInvariant();
        var mimeType = ext switch
        {
            ".mp4" or ".m4a" => "audio/mp4",
            ".wav"           => "audio/wav",
            ".ogg"           => "audio/ogg",
            ".flac"          => "audio/flac",
            _                => "audio/mpeg"
        };

        return PhysicalFile(actualFilePath, mimeType, true);
    }

    private ValueTask QueueTrackAnalysisAsync(Guid trackId)
    {
        return _taskQueue.QueueBackgroundWorkItemAsync(async (sp, token) =>
        {
            using var scope = sp.CreateScope();
            var analysisService = scope.ServiceProvider.GetRequiredService<TrackAnalysisService>();
            await analysisService.ProcessTrackAsync(trackId, token);
        });
    }
}
