using System.Net.Http.Json;
using System.Net.Http.Headers;
using System.Text.Json;
using Microsoft.Extensions.Options;
using MixerAI.Web.Configuration;
using MixerAI.Web.Models;

namespace MixerAI.Web.Services;

public sealed class MixerBackendClient
{
    private readonly HttpClient _httpClient;

    public MixerBackendClient(HttpClient httpClient, IOptions<BackendApiOptions> options)
    {
        _httpClient = httpClient;
        _httpClient.BaseAddress = new Uri(options.Value.BaseUrl);
    }

    public async Task<MixJobResultViewModel> CreateMixJobAsync(
        string title,
        IFormFile trackA,
        IFormFile trackB,
        CancellationToken cancellationToken)
    {
        using var content = new MultipartFormDataContent();
        content.Add(new StringContent(title), "title");
        content.Add(await CreateFileContentAsync(trackA, cancellationToken), "trackA", trackA.FileName);
        content.Add(await CreateFileContentAsync(trackB, cancellationToken), "trackB", trackB.FileName);

        using var response = await _httpClient.PostAsync("/api/mix-jobs", content, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new InvalidOperationException($"Backend rejected the mix job: {error}");
        }

        var result = await response.Content.ReadFromJsonAsync<MixJobResultViewModel>(cancellationToken: cancellationToken);
        return result ?? throw new InvalidOperationException("Backend returned an empty response.");
    }

    public async Task<(byte[] Content, string FileName)> RenderMixAsync(
        IFormFile trackA,
        IFormFile trackB,
        double? overlayStartSeconds,
        double? rightStartSeconds,
        CancellationToken cancellationToken)
    {
        using var content = new MultipartFormDataContent();
        content.Add(await CreateFileContentAsync(trackA, cancellationToken), "trackA", trackA.FileName);
        content.Add(await CreateFileContentAsync(trackB, cancellationToken), "trackB", trackB.FileName);
        if (overlayStartSeconds is double overlay)
        {
            content.Add(new StringContent(overlay.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)), "overlayStartSeconds");
        }
        if (rightStartSeconds is double right)
        {
            content.Add(new StringContent(right.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)), "rightStartSeconds");
        }

        using var response = await _httpClient.PostAsync("/api/mix/render", content, cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new InvalidOperationException(ParseBackendError(error));
        }

        var fileName = response.Content.Headers.ContentDisposition?.FileNameStar
            ?? response.Content.Headers.ContentDisposition?.FileName?.Trim('"')
            ?? "mixerai-mix.mp3";

        return (await response.Content.ReadAsByteArrayAsync(cancellationToken), fileName);
    }

    public async Task<MixAnalysisResultViewModel> AnalyzeMixAsync(
        IFormFile trackA,
        IFormFile trackB,
        CancellationToken cancellationToken)
    {
        using var content = new MultipartFormDataContent();
        content.Add(await CreateFileContentAsync(trackA, cancellationToken), "trackA", trackA.FileName);
        content.Add(await CreateFileContentAsync(trackB, cancellationToken), "trackB", trackB.FileName);

        using var response = await _httpClient.PostAsync("/api/mix/analyze", content, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new InvalidOperationException(ParseBackendError(error));
        }

        var result = await response.Content.ReadFromJsonAsync<MixAnalysisResultViewModel>(cancellationToken: cancellationToken);
        return result ?? throw new InvalidOperationException("Backend returned an empty analysis response.");
    }

    public async Task<(byte[] Content, string FileName)> GenerateTrackAsync(
        string style,
        int durationSeconds,
        int? seed,
        CancellationToken cancellationToken)
    {
        var payload = new
        {
            style,
            durationSeconds,
            seed,
        };
        using var response = await _httpClient.PostAsJsonAsync("/api/generate-track", payload, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new InvalidOperationException(ParseBackendError(error));
        }

        var fileName = response.Content.Headers.ContentDisposition?.FileNameStar
            ?? response.Content.Headers.ContentDisposition?.FileName?.Trim('"')
            ?? $"beatmix-{style}.mp3";

        return (await response.Content.ReadAsByteArrayAsync(cancellationToken), fileName);
    }

    public async Task<(byte[] Content, string FileName)> GenerateMiniMixAsync(
        int? seed,
        CancellationToken cancellationToken)
    {
        var url = seed.HasValue ? $"/api/generate-mini-mix?seed={seed.Value}" : "/api/generate-mini-mix";
        using var response = await _httpClient.PostAsync(url, null, cancellationToken);
        
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new InvalidOperationException(ParseBackendError(error));
        }

        var fileName = response.Content.Headers.ContentDisposition?.FileNameStar
            ?? response.Content.Headers.ContentDisposition?.FileName?.Trim('"')
            ?? "minimix.mp3";

        return (await response.Content.ReadAsByteArrayAsync(cancellationToken), fileName);
    }

    private static string ParseBackendError(string payload)
    {
        try
        {
            using var document = JsonDocument.Parse(payload);
            if (document.RootElement.TryGetProperty("error", out var errorProperty))
            {
                var message = errorProperty.GetString() ?? "Backend rejected render request.";
                return ShortenError(message);
            }
        }
        catch (JsonException)
        {
        }

        return ShortenError(payload);
    }

    private static string ShortenError(string message)
    {
        const string prefix = "Backend rejected render request: ";
        if (string.IsNullOrWhiteSpace(message))
        {
            return $"{prefix}Unknown error.";
        }

        var normalized = message.Replace("\r", " ").Replace("\n", " ").Trim();
        if (normalized.Length > 240)
        {
            normalized = normalized[..240] + "...";
        }

        return prefix + normalized;
    }

    private static async Task<StreamContent> CreateFileContentAsync(IFormFile file, CancellationToken cancellationToken)
    {
        var stream = new MemoryStream();
        await file.CopyToAsync(stream, cancellationToken);
        stream.Position = 0;

        var content = new StreamContent(stream);
        content.Headers.ContentType = new(file.ContentType == string.Empty ? "application/octet-stream" : file.ContentType);
        return content;
    }
}
