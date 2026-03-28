using System.Diagnostics;
using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Models;
using MixerAI.Web.Services;

namespace MixerAI.Web.Controllers;

public class HomeController : Controller
{
    private const string GenerationErrorTempDataKey = "GenerationErrorMessage";

    private readonly IMixerBackendClient _backendClient;

    public HomeController(IMixerBackendClient backendClient)
    {
        _backendClient = backendClient;
    }

    [HttpGet]
    public async Task<IActionResult> Index(CancellationToken cancellationToken)
    {
        var workspace = await BuildWorkspaceAsync(cancellationToken: cancellationToken);
        return View(workspace);
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> RenderMix([FromForm] Guid trackAId, [FromForm] Guid trackBId, CancellationToken cancellationToken)
    {
        try
        {
            var result = await _backendClient.RenderMixFromLibraryAsync(trackAId, trackBId, cancellationToken);
            return File(result, "audio/mpeg", "mixerai-mix.mp3");
        }
        catch (Exception ex)
        {
            return BadRequest(ex.Message);
        }
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> RecommendTransitions(
        [Bind(Prefix = "Recommendation")] TransitionRecommendationRequestViewModel model,
        CancellationToken cancellationToken)
    {
        if (!ValidateSubModel(model, nameof(StudioWorkspaceViewModel.Recommendation)))
        {
            var invalidWorkspace = await BuildWorkspaceAsync(recommendation: model, cancellationToken: cancellationToken);
            return View("Index", invalidWorkspace);
        }

        try
        {
            var results = await _backendClient.RecommendTransitionsAsync(model, cancellationToken);
            var workspace = await BuildWorkspaceAsync(
                recommendation: model,
                recommendationResults: results,
                cancellationToken: cancellationToken);
            return View("Index", workspace);
        }
        catch (Exception exception)
        {
            var workspace = await BuildWorkspaceAsync(
                recommendation: model,
                recommendationErrorMessage: exception.Message,
                cancellationToken: cancellationToken);
            return View("Index", workspace);
        }
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> GenerateTrack(
        [Bind(Prefix = "Generation")] MixStudioViewModel model,
        CancellationToken cancellationToken)
    {
        if (!ValidateSubModel(model, nameof(StudioWorkspaceViewModel.Generation)))
        {
            var invalidWorkspace = await BuildWorkspaceAsync(generation: model, cancellationToken: cancellationToken);
            return View("Index", invalidWorkspace);
        }

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
            TempData[GenerationErrorTempDataKey] = exception.Message;
            return RedirectToAction(nameof(Index));
        }
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> GenerateMiniMix(
        [Bind(Prefix = "Generation")] MixStudioViewModel model,
        CancellationToken cancellationToken)
    {
        try
        {
            var result = await _backendClient.GenerateMiniMixAsync(model.GeneratedTrackSeed, cancellationToken);
            return File(result.Content, "audio/mpeg", result.FileName);
        }
        catch (Exception exception)
        {
            TempData[GenerationErrorTempDataKey] = exception.Message;
            return RedirectToAction(nameof(Index));
        }
    }

    [ResponseCache(Duration = 0, Location = ResponseCacheLocation.None, NoStore = true)]
    public IActionResult Error()
    {
        return View(new ErrorViewModel { RequestId = Activity.Current?.Id ?? HttpContext.TraceIdentifier });
    }

    private async Task<StudioWorkspaceViewModel> BuildWorkspaceAsync(
        MixStudioViewModel? generation = null,
        TransitionRecommendationRequestViewModel? recommendation = null,
        IReadOnlyList<TransitionRecommendationViewModel>? recommendationResults = null,
        string? recommendationErrorMessage = null,
        CancellationToken cancellationToken = default)
    {
        var tracks = await _backendClient.GetTracksAsync(cancellationToken);
        var setIds = await _backendClient.GetAvailableSetIdsAsync(cancellationToken);

        var recommendationModel = recommendation ?? BuildDefaultRecommendation(setIds);
        var generationModel = generation ?? new MixStudioViewModel();

        var generationErrorMessage = TempData[GenerationErrorTempDataKey] as string;

        return new StudioWorkspaceViewModel
        {
            Tracks = tracks,
            AvailableSetIds = setIds,
            Generation = generationModel,
            Recommendation = recommendationModel,
            RecommendationResults = recommendationResults ?? [],
            RecommendationErrorMessage = recommendationErrorMessage,
            GenerationErrorMessage = generationErrorMessage
        };
    }

    private static TransitionRecommendationRequestViewModel BuildDefaultRecommendation(IReadOnlyList<string> setIds)
    {
        var leftSetId = setIds.ElementAtOrDefault(0) ?? string.Empty;
        var rightSetId = setIds.ElementAtOrDefault(1) ?? leftSetId;

        return new TransitionRecommendationRequestViewModel
        {
            LeftSetId = leftSetId,
            RightSetId = rightSetId,
            TopK = 5
        };
    }

    private bool ValidateSubModel<TModel>(TModel model, string prefix)
    {
        var validationResults = new List<ValidationResult>();
        var validationContext = new ValidationContext(model!);
        var isValid = Validator.TryValidateObject(model!, validationContext, validationResults, validateAllProperties: true);

        if (isValid)
        {
            return true;
        }

        foreach (var validationResult in validationResults)
        {
            var members = validationResult.MemberNames.Any() ? validationResult.MemberNames : [string.Empty];
            foreach (var member in members)
            {
                var key = string.IsNullOrWhiteSpace(member) ? prefix : $"{prefix}.{member}";
                ModelState.AddModelError(key, validationResult.ErrorMessage ?? "Validation failed.");
            }
        }

        return false;
    }
}
