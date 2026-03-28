using System.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Models;
using MixerAI.Web.Services;

namespace MixerAI.Web.Controllers;

public class HomeController : Controller
{
    private const string GenerationErrorTempDataKey = "GenerationErrorMessage";

    private readonly MixerBackendClient _backendClient;

    public HomeController(MixerBackendClient backendClient)
    {
        _backendClient = backendClient;
    }

    [HttpGet]
    public IActionResult Index()
    {
        return View(new MixStudioViewModel
        {
            ErrorMessage = TempData[GenerationErrorTempDataKey] as string
        });
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> GenerateTrack(MixStudioViewModel model, CancellationToken cancellationToken)
    {
        if (!ModelState.IsValid)
        {
            return View("Index", model);
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
    public async Task<IActionResult> GenerateMiniMix(MixStudioViewModel model, CancellationToken cancellationToken)
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
}
