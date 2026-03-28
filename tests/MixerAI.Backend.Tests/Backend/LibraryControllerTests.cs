using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using MixerAI.Backend.Controllers;
using MixerAI.Backend.Data;
using MixerAI.Backend.Entities;

namespace MixerAI.Backend.Tests.Backend;

public class LibraryControllerTests
{
    [Fact]
    public async Task UploadTrack_SavesTrackAndQueuesAnalysis()
    {
        await using var db = CreateDbContext();
        var queue = new FakeBackgroundTaskQueue();
        var env = new TestHostEnvironment();
        Directory.CreateDirectory(env.ContentRootPath);

        var controller = new LibraryController(db, queue, env)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestHelpers.CreateHttpContext(new Claim(ClaimTypes.NameIdentifier, "user-1"))
            }
        };

        await using var stream = new MemoryStream([1, 2, 3, 4]);
        IFormFile file = new FormFile(stream, 0, stream.Length, "file", "roller.mp3")
        {
            Headers = new HeaderDictionary(),
            ContentType = "audio/mpeg"
        };

        var result = await controller.UploadTrack(file, CancellationToken.None);

        var accepted = Assert.IsType<AcceptedResult>(result);
        var createdTrack = Assert.IsType<Track>(accepted.Value);
        var storedTrack = await db.Tracks.SingleAsync();

        Assert.Equal(createdTrack.Id, storedTrack.Id);
        Assert.Equal("roller", storedTrack.Title);
        Assert.Equal("Pending", storedTrack.Status);
        Assert.Single(queue.WorkItems);
        Assert.True(File.Exists(Path.Combine(env.ContentRootPath, "App_Data", "UserTracks", storedTrack.FilePath)));
    }

    [Fact]
    public async Task RetryTrackAnalysis_ResetsErrorAndQueuesTrack()
    {
        await using var db = CreateDbContext();
        var queue = new FakeBackgroundTaskQueue();
        var env = new TestHostEnvironment();
        Directory.CreateDirectory(Path.Combine(env.ContentRootPath, "App_Data", "UserTracks"));

        var track = new Track
        {
            Id = Guid.NewGuid(),
            Title = "Needs retry",
            FilePath = "retry.mp3",
            Status = "Error",
            UserId = "user-1",
            LastAnalysisError = "ffmpeg failed",
            AnalysisAttempts = 1
        };
        db.Tracks.Add(track);
        await db.SaveChangesAsync();

        var controller = new LibraryController(db, queue, env)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestHelpers.CreateHttpContext(new Claim(ClaimTypes.NameIdentifier, "user-1"))
            }
        };

        var result = await controller.RetryTrackAnalysis(track.Id, CancellationToken.None);

        Assert.IsType<AcceptedResult>(result);
        var refreshed = await db.Tracks.SingleAsync();
        Assert.Equal("Pending", refreshed.Status);
        Assert.Null(refreshed.LastAnalysisError);
        Assert.Single(queue.WorkItems);
    }

    private static ApplicationDbContext CreateDbContext()
    {
        var options = new DbContextOptionsBuilder<ApplicationDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString("N"))
            .Options;
        return new ApplicationDbContext(options);
    }
}
