using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Controllers;
using MixerAI.Web.Models;

namespace MixerAI.Backend.Tests.Web;

public class HomeControllerTests
{
    [Fact]
    public async Task Index_ReturnsWorkspaceModelWithTracksAndSetIds()
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

        var result = await controller.Index(CancellationToken.None);

        var view = Assert.IsType<ViewResult>(result);
        var model = Assert.IsType<StudioWorkspaceViewModel>(view.Model);
        Assert.Single(model.Tracks);
        Assert.Equal(2, model.AvailableSetIds.Count);
        Assert.Equal("Set One", model.Recommendation.LeftSetId);
    }

    [Fact]
    public async Task GenerateTrack_InvalidModel_ReturnsIndexViewWithWorkspaceModel()
    {
        var backend = new FakeMixerBackendClient
        {
            Tracks = [new TrackViewModel { Id = Guid.NewGuid(), Title = "Track A", Status = "Ready" }],
            SetIds = ["Set One", "Set Two"]
        };
        var controller = CreateController(backend);

        var result = await controller.GenerateTrack(new MixStudioViewModel
        {
            GeneratedTrackStyle = "liquid",
            GeneratedTrackDurationSeconds = 12
        }, CancellationToken.None);

        var view = Assert.IsType<ViewResult>(result);
        Assert.Equal("Index", view.ViewName);
        var model = Assert.IsType<StudioWorkspaceViewModel>(view.Model);
        Assert.Equal(0, backend.GenerateTrackCalls);
        Assert.Equal(12, model.Generation.GeneratedTrackDurationSeconds);
    }

    [Fact]
    public async Task RecommendTransitions_ReturnsRecommendationResults()
    {
        var backend = new FakeMixerBackendClient
        {
            Tracks = [],
            SetIds = ["Set One", "Set Two"],
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

        var view = Assert.IsType<ViewResult>(result);
        var model = Assert.IsType<StudioWorkspaceViewModel>(view.Model);
        Assert.Single(model.RecommendationResults);
        Assert.Equal(0.81, model.RecommendationResults[0].Probability);
    }

    [Fact]
    public async Task RenderMix_ReturnsAudioFile()
    {
        var backend = new FakeMixerBackendClient
        {
            RenderedMix = [9, 8, 7]
        };
        var controller = CreateController(backend);

        var result = await controller.RenderMix(Guid.NewGuid(), Guid.NewGuid(), CancellationToken.None);

        var file = Assert.IsType<FileContentResult>(result);
        Assert.Equal("audio/mpeg", file.ContentType);
        Assert.Equal([9, 8, 7], file.FileContents);
    }

    private static HomeController CreateController(FakeMixerBackendClient backend)
    {
        var controller = new HomeController(backend);
        var httpContext = TestHelpers.CreateHttpContext();
        controller.ControllerContext = new ControllerContext { HttpContext = httpContext };
        controller.TempData = TestHelpers.CreateTempData(httpContext);
        return controller;
    }
}
