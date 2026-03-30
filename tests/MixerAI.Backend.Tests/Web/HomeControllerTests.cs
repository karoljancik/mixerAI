using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Contracts;
using MixerAI.Web.Controllers;
using MixerAI.Web.Models;
using MixerAI.Web.Workspace;

namespace MixerAI.Backend.Tests.Web;

public class HomeControllerTests
{
    [Fact]
    public async Task GetWorkspace_ReturnsSnapshotWithTracksAndSetIds()
    {
        var backend = new FakeMixerBackendClient
        {
            Tracks =
            [
                new TrackViewModel { Id = Guid.NewGuid(), Title = "Track A", Status = "Ready" }
            ],
            SetIds = ["Set One", "Set Two"]
        };
        var controller = CreateController(backend);

        var result = await controller.GetWorkspace(CancellationToken.None);

        var ok = Assert.IsType<OkObjectResult>(result.Result);
        var model = Assert.IsType<WorkspaceSnapshotResponse>(ok.Value);
        Assert.Single(model.Tracks);
        Assert.Equal(2, model.AvailableSetIds.Count);
        Assert.Equal(1, model.ReadyTrackCount);
    }

    [Fact]
    public async Task RecommendTransitions_ReturnsRecommendationResults()
    {
        var backend = new FakeMixerBackendClient
        {
            Recommendations =
            [
                new TransitionRecommendationViewModel
                {
                    LeftSetId = "Set One",
                    RightSetId = "Set Two",
                    LeftStartSeconds = 32.5,
                    RightStartSeconds = 18.0,
                    Probability = 0.81
                }
            ]
        };
        var controller = CreateController(backend);

        var result = await controller.RecommendTransitions(new TransitionRecommendationRequestViewModel
        {
            LeftSetId = "Set One",
            RightSetId = "Set Two",
            TopK = 3
        }, CancellationToken.None);

        var ok = Assert.IsType<OkObjectResult>(result.Result);
        var model = Assert.IsAssignableFrom<IReadOnlyList<TransitionRecommendationViewModel>>(ok.Value);
        Assert.Single(model);
        Assert.Equal(0.81, model[0].Probability);
    }

    [Fact]
    public async Task RenderMix_ReturnsAudioFile()
    {
        var backend = new FakeMixerBackendClient
        {
            RenderedMix = [9, 8, 7]
        };
        var controller = CreateController(backend);

        var result = await controller.RenderMix(new RenderMixRequest
        {
            TrackAId = Guid.NewGuid(),
            TrackBId = Guid.NewGuid()
        }, CancellationToken.None);

        var file = Assert.IsType<FileContentResult>(result);
        Assert.Equal("audio/mpeg", file.ContentType);
        Assert.Equal([9, 8, 7], file.FileContents);
    }

    private static WorkspaceController CreateController(FakeMixerBackendClient backend)
    {
        var controller = new WorkspaceController(backend, new WorkspaceSnapshotBuilder(backend));
        controller.ControllerContext = new ControllerContext
        {
            HttpContext = TestHelpers.CreateHttpContext()
        };
        return controller;
    }
}
