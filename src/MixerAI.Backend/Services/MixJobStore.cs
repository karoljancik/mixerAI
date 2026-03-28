using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.AspNetCore.Http;
using MixerAI.Backend.Models;

namespace MixerAI.Backend.Services;

public sealed class MixJobStore
{
    private static readonly HashSet<string> AllowedExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".mp3",
        ".wav",
        ".flac",
        ".aiff"
    };

    private readonly ConcurrentDictionary<Guid, MixJobRecord> _jobs = new();
    private readonly string _jobsRoot;

    public MixJobStore(IHostEnvironment environment)
    {
        _jobsRoot = Path.Combine(environment.ContentRootPath, "App_Data", "MixJobs");
        Directory.CreateDirectory(_jobsRoot);
    }

    public MixJobRecord? Get(Guid id) => _jobs.TryGetValue(id, out var job) ? job : null;

    public async Task<MixJobRecord> CreateAsync(
        string title,
        IFormFile trackA,
        IFormFile trackB,
        CancellationToken cancellationToken)
    {
        ValidateFile(trackA, "trackA");
        ValidateFile(trackB, "trackB");

        var jobId = Guid.NewGuid();
        var workingDirectory = Path.Combine(_jobsRoot, jobId.ToString("N"));
        Directory.CreateDirectory(workingDirectory);

        var trackAPath = Path.Combine(workingDirectory, $"track-a{Path.GetExtension(trackA.FileName)}");
        var trackBPath = Path.Combine(workingDirectory, $"track-b{Path.GetExtension(trackB.FileName)}");

        await SaveAsync(trackA, trackAPath, cancellationToken);
        await SaveAsync(trackB, trackBPath, cancellationToken);

        var manifestPath = Path.Combine(workingDirectory, "mix-job.json");
        var job = new MixJobRecord
        {
            Id = jobId,
            Title = string.IsNullOrWhiteSpace(title) ? $"Mix job {jobId:N}" : title.Trim(),
            Status = "Uploaded",
            CreatedAtUtc = DateTime.UtcNow,
            TrackAFileName = Path.GetFileName(trackA.FileName),
            TrackBFileName = Path.GetFileName(trackB.FileName),
            WorkingDirectory = workingDirectory,
            ManifestPath = manifestPath
        };

        await File.WriteAllTextAsync(
            manifestPath,
            JsonSerializer.Serialize(job, new JsonSerializerOptions { WriteIndented = true }),
            cancellationToken);

        _jobs[jobId] = job;
        return job;
    }

    private static void ValidateFile(IFormFile file, string fieldName)
    {
        if (file.Length == 0)
        {
            throw new BadHttpRequestException($"{fieldName} is empty.");
        }

        var extension = Path.GetExtension(file.FileName);
        if (!AllowedExtensions.Contains(extension))
        {
            throw new BadHttpRequestException($"{fieldName} has unsupported format.");
        }
    }

    private static async Task SaveAsync(IFormFile file, string destinationPath, CancellationToken cancellationToken)
    {
        await using var targetStream = File.Create(destinationPath);
        await using var sourceStream = file.OpenReadStream();
        await sourceStream.CopyToAsync(targetStream, cancellationToken);
    }
}
