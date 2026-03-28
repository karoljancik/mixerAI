using MixerAI.Backend.Data;
using MixerAI.Backend.Entities;
using MixerAI.Backend.Models;
using Microsoft.EntityFrameworkCore;

namespace MixerAI.Backend.Services;

public class MixJobStore
{
    private readonly ApplicationDbContext _db;
    private readonly AiMixRenderService _renderService;
    private readonly string _rendersRoot;

    public MixJobStore(ApplicationDbContext db, AiMixRenderService renderService, IHostEnvironment env)
    {
        _db = db;
        _renderService = renderService;
        _rendersRoot = Path.Combine(env.ContentRootPath, "App_Data", "RenderedMixes");
        Directory.CreateDirectory(_rendersRoot);
    }

    public async Task<MixJobRecord> CreateAsync(string title, Guid trackAId, Guid trackBId, string userId, CancellationToken ct)
    {
        var trackA = await _db.Tracks.FirstAsync(t => t.Id == trackAId && t.UserId == userId, ct);
        var trackB = await _db.Tracks.FirstAsync(t => t.Id == trackBId && t.UserId == userId, ct);

        var job = new MixJob
        {
            Id = Guid.NewGuid(),
            Title = title,
            TrackAId = trackAId,
            TrackBId = trackBId,
            UserId = userId,
            CreatedAtUtc = DateTime.UtcNow,
            Status = "Queued"
        };

        _db.MixJobs.Add(job);
        await _db.SaveChangesAsync(ct);
        
        return ToRecord(job);
    }

    public async Task<MixJobRecord?> GetAsync(Guid id, string userId, CancellationToken ct)
    {
        var job = await _db.MixJobs
            .Include(j => j.TrackA)
            .Include(j => j.TrackB)
            .FirstOrDefaultAsync(j => j.Id == id && j.UserId == userId, ct);
        
        return job == null ? null : ToRecord(job);
    }

    public async Task<List<MixJobRecord>> GetUserJobsAsync(string userId, CancellationToken ct)
    {
        var jobs = await _db.MixJobs
            .Where(j => j.UserId == userId)
            .OrderByDescending(j => j.CreatedAtUtc)
            .ToListAsync(ct);
            
        return jobs.Select(ToRecord).ToList();
    }

    private static MixJobRecord ToRecord(MixJob j) => new MixJobRecord {
        Id = j.Id,
        Title = j.Title,
        Status = j.Status,
        CreatedAtUtc = j.CreatedAtUtc
    };
}
