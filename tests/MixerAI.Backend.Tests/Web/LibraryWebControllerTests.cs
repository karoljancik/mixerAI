using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Controllers;

namespace MixerAI.Backend.Tests.Web;

public class LibraryWebControllerTests
{
    [Fact]
    public async Task Retry_ReturnsAcceptedWhenBackendAccepts()
    {
        var backend = new FakeMixerBackendClient { RetryTrackAnalysisResult = true };
        var controller = new LibraryController(backend);

        var result = await controller.Retry(Guid.NewGuid());

        Assert.IsType<AcceptedResult>(result);
    }

    [Fact]
    public async Task Upload_RedirectsToIndexAndCallsBackend()
    {
        var backend = new FakeMixerBackendClient();
        var controller = new LibraryController(backend);

        await using var stream = new MemoryStream([1, 2, 3]);
        IFormFile file = new FormFile(stream, 0, stream.Length, "file", "idea.mp3");

        var result = await controller.Upload(file);

        var redirect = Assert.IsType<RedirectToActionResult>(result);
        Assert.Equal("Index", redirect.ActionName);
        Assert.Equal(1, backend.UploadCalls);
    }
}
