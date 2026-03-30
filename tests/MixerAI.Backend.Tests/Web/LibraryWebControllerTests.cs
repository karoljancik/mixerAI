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
        var controller = CreateController(backend);

        var result = await controller.Retry(Guid.NewGuid(), CancellationToken.None);

        Assert.IsType<AcceptedResult>(result);
    }

    [Fact]
    public async Task Upload_ReturnsCreatedAndCallsBackend()
    {
        var backend = new FakeMixerBackendClient();
        var controller = CreateController(backend);

        await using var stream = new MemoryStream([1, 2, 3]);
        IFormFile file = new FormFile(stream, 0, stream.Length, "file", "idea.mp3");

        var result = await controller.Upload(file, CancellationToken.None);

        Assert.IsType<CreatedAtActionResult>(result);
        Assert.Equal(1, backend.UploadCalls);
    }

    private static LibraryController CreateController(FakeMixerBackendClient backend)
    {
        return new LibraryController(backend)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestHelpers.CreateHttpContext()
            }
        };
    }
}
