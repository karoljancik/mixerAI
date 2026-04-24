using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Contracts;
using MixerAI.Web.Models;
using MixerAI.Web.Services;
using MixerAI.Web.Workspace;

namespace MixerAI.Web.Controllers;

[ApiController]
[Authorize]
[Route("api/bff/workspace")]
public sealed class WorkspaceController : ControllerBase
{
    private readonly IMixerBackendClient _backendClient;
    private readonly WorkspaceSnapshotBuilder _snapshotBuilder;

    public WorkspaceController(IMixerBackendClient backendClient, WorkspaceSnapshotBuilder snapshotBuilder)
    {
        _backendClient = backendClient;
        _snapshotBuilder = snapshotBuilder;
    }

    [HttpGet]
    public async Task<ActionResult<WorkspaceSnapshotResponse>> GetWorkspace(CancellationToken cancellationToken)
    {
        return Ok(await _snapshotBuilder.BuildAsync(User, cancellationToken));
    }

    [HttpPost("render-mix")]
    public async Task<IActionResult> RenderMix([FromBody] RenderMixRequest request, CancellationToken cancellationToken)
    {
        try
        {
            var result = await _backendClient.RenderMixFromLibraryAsync(
                request.TrackAId,
                request.TrackBId,
                request.OverlayStartSeconds,
                request.RightStartSeconds,
                cancellationToken);
            return File(result, "audio/mpeg", "mixerai-transition-reference.mp3");
        }
        catch (Exception exception)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = exception.Message
            });
        }
    }

    [HttpPost("analyze-mix")]
    [RequestSizeLimit(250_000_000)]
    public async Task<ActionResult<MixAnalysisResultViewModel>> AnalyzeMix(
        [FromForm] IFormFile? trackA,
        [FromForm] IFormFile? trackB,
        CancellationToken cancellationToken)
    {
        if (trackA is null || trackB is null)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = "Upload both tracks before requesting analysis."
            });
        }

        try
        {
            return Ok(await _backendClient.AnalyzeMixAsync(trackA, trackB, cancellationToken));
        }
        catch (Exception exception)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = exception.Message
            });
        }
    }

    [HttpPost("recommendations")]
    public async Task<ActionResult<IReadOnlyList<TransitionRecommendationViewModel>>> RecommendTransitions(
        [FromBody] TransitionRecommendationRequestViewModel model,
        CancellationToken cancellationToken)
    {
        try
        {
            return Ok(await _backendClient.RecommendTransitionsAsync(model, cancellationToken));
        }
        catch (Exception exception)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = exception.Message
            });
        }
    }

    [HttpPost("generate-track")]
    public async Task<IActionResult> GenerateTrack([FromBody] MixStudioViewModel model, CancellationToken cancellationToken)
    {
        try
        {
            var result = await _backendClient.GenerateTrackAsync(
                model.GeneratedTrackStyle,
                model.GeneratedTrackDurationSeconds,
                model.GeneratedTrackSeed,
                cancellationToken);
            return File(result.Content, "audio/mpeg", result.FileName);
        }
        catch (Exception exception)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = exception.Message
            });
        }
    }

    [HttpPost("generate-mini-mix")]
    public async Task<IActionResult> GenerateMiniMix([FromBody] MixStudioViewModel model, CancellationToken cancellationToken)
    {
        try
        {
            var result = await _backendClient.GenerateMiniMixAsync(model.GeneratedTrackSeed, cancellationToken);
            return File(result.Content, "audio/mpeg", result.FileName);
        }
        catch (Exception exception)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = exception.Message
            });
        }
    }
}

public sealed class RenderMixRequest
{
    public Guid TrackAId { get; init; }
    public Guid TrackBId { get; init; }
    public double? OverlayStartSeconds { get; init; }
    public double? RightStartSeconds { get; init; }
}
