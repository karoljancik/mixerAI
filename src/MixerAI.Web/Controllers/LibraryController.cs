using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Services;

namespace MixerAI.Web.Controllers;

[Authorize]
public class LibraryController : Controller
{
    private readonly IMixerBackendClient _backend;

    public LibraryController(IMixerBackendClient backend)
    {
        _backend = backend;
    }

    public async Task<IActionResult> Index()
    {
        var tracks = await _backend.GetTracksAsync();
        return View(tracks);
    }

    [HttpPost]
    public async Task<IActionResult> Upload(IFormFile file)
    {
        if (file == null || file.Length == 0) return RedirectToAction(nameof(Index));
        await _backend.UploadTrackAsync(file);
        return RedirectToAction(nameof(Index));
    }

    [HttpPost("/Library/delete/{id:guid}")]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Delete(Guid id)
    {
        var ok = await _backend.DeleteTrackAsync(id);
        return ok ? Ok() : NotFound();
    }

    [HttpPost("/Library/retry/{id:guid}")]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Retry(Guid id)
    {
        var ok = await _backend.RetryTrackAnalysisAsync(id);
        return ok ? Accepted() : BadRequest();
    }

    /// <summary>
    /// Same-origin audio proxy — avoids CORS by serving audio from port 5000 instead of 8080.
    /// </summary>
    [HttpGet("/Library/audio/{id:guid}")]
    public async Task<IActionResult> GetAudio(Guid id, CancellationToken cancellationToken)
    {
        var result = await _backend.GetTrackAudioStreamAsync(id, cancellationToken);
        if (result == null) return NotFound();

        Response.Headers["Accept-Ranges"] = "bytes";
        Response.Headers["Cache-Control"] = "private, max-age=3600";
        return File(result.Value.Stream, result.Value.ContentType, enableRangeProcessing: true);
    }
}
