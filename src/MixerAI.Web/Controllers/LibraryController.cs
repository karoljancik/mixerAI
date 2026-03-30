using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Contracts;
using MixerAI.Web.Services;

namespace MixerAI.Web.Controllers;

[ApiController]
[Authorize]
[Route("api/bff/library")]
public sealed class LibraryController : ControllerBase
{
    private readonly IMixerBackendClient _backendClient;

    public LibraryController(IMixerBackendClient backendClient)
    {
        _backendClient = backendClient;
    }

    [HttpGet]
    public async Task<IActionResult> GetTracks(CancellationToken cancellationToken)
    {
        return Ok(await _backendClient.GetTracksAsync(cancellationToken));
    }

    [HttpPost("upload")]
    public async Task<IActionResult> Upload([FromForm] IFormFile? file, CancellationToken cancellationToken)
    {
        if (file is null || file.Length == 0)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = "Choose an audio file before uploading."
            });
        }

        var createdTrack = await _backendClient.UploadTrackAsync(file, cancellationToken);
        return CreatedAtAction(nameof(GetTracks), new { id = createdTrack.Id }, createdTrack);
    }

    [HttpDelete("{id:guid}")]
    public async Task<IActionResult> Delete(Guid id, CancellationToken cancellationToken)
    {
        var deleted = await _backendClient.DeleteTrackAsync(id, cancellationToken);
        return deleted ? NoContent() : NotFound();
    }

    [HttpPost("{id:guid}/retry-analysis")]
    public async Task<IActionResult> Retry(Guid id, CancellationToken cancellationToken)
    {
        var accepted = await _backendClient.RetryTrackAnalysisAsync(id, cancellationToken);
        return accepted ? Accepted() : BadRequest();
    }

    [HttpGet("audio/{id:guid}")]
    public async Task<IActionResult> GetAudio(Guid id, CancellationToken cancellationToken)
    {
        var result = await _backendClient.GetTrackAudioStreamAsync(id, cancellationToken);
        if (result == null)
        {
            return NotFound();
        }

        Response.Headers["Accept-Ranges"] = "bytes";
        Response.Headers["Cache-Control"] = "private, max-age=3600";
        return File(result.Value.Stream, result.Value.ContentType, enableRangeProcessing: true);
    }
}
