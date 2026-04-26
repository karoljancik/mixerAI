using System.Net.Http.Json;
using System.Net.Http.Headers;
using System.Text.Json;
using Microsoft.Extensions.Options;
using MixerAI.Web.Configuration;
using MixerAI.Web.Models;

namespace MixerAI.Web.Services;

public sealed class MixerBackendClient : IMixerBackendClient
{
    private readonly HttpClient _httpClient;
    private readonly Microsoft.AspNetCore.Http.IHttpContextAccessor _httpContextAccessor;

    public MixerBackendClient(HttpClient httpClient, IOptions<BackendApiOptions> options, Microsoft.AspNetCore.Http.IHttpContextAccessor httpContextAccessor)
    {
        _httpClient = httpClient;
        _httpClient.BaseAddress = new Uri(options.Value.BaseUrl);
        _httpContextAccessor = httpContextAccessor;
    }

    public async Task<bool> RegisterAsync(string email, string password)
    {
        var payload = new { email, password };
        var response = await _httpClient.PostAsJsonAsync("/register", payload);
        return response.IsSuccessStatusCode;
    }

    public sealed record LoginResponse(bool IsSuccess, string Token = "");

    public async Task<LoginResponse> LoginAsync(string email, string password)
    {
        var payload = new { email, password };
        var response = await _httpClient.PostAsJsonAsync("/login?useCookies=false", payload);
        
        if (!response.IsSuccessStatusCode)
            return new LoginResponse(false);

        var result = await response.Content.ReadFromJsonAsync<IdentityLoginResult>();
        return new LoginResponse(true, result?.AccessToken ?? "");
    }

    private sealed record IdentityLoginResult(string AccessToken);
    private sealed record BackendTransitionRecommendation(
        [property: System.Text.Json.Serialization.JsonPropertyName("left_set_id")] string LeftSetId,
        [property: System.Text.Json.Serialization.JsonPropertyName("left_segment_index")] int LeftSegmentIndex,
        [property: System.Text.Json.Serialization.JsonPropertyName("left_start_seconds")] double LeftStartSeconds,
        [property: System.Text.Json.Serialization.JsonPropertyName("right_set_id")] string RightSetId,
        [property: System.Text.Json.Serialization.JsonPropertyName("right_segment_index")] int RightSegmentIndex,
        [property: System.Text.Json.Serialization.JsonPropertyName("right_start_seconds")] double RightStartSeconds,
        [property: System.Text.Json.Serialization.JsonPropertyName("probability")] double Probability);

    // --- LIBRARY OPERATIONS ---
    public async Task<List<TrackViewModel>> GetTracksAsync(CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedRequest(HttpMethod.Get, "/api/tracks");
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<List<TrackViewModel>>(cancellationToken) ?? [];
    }

    public async Task<TrackViewModel> UploadTrackAsync(IFormFile file, CancellationToken cancellationToken = default)
    {
        using var content = new MultipartFormDataContent();
        content.Add(await CreateFileContentAsync(file, cancellationToken), "file", file.FileName);
        
        using var request = CreateAuthorizedRequest(HttpMethod.Post, "/api/tracks/upload", content);
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        
        return await response.Content.ReadFromJsonAsync<TrackViewModel>(cancellationToken) 
               ?? throw new InvalidOperationException("Empty response from track upload.");
    }

    public string GetTrackFileUrl(Guid trackId) => $"{_httpClient.BaseAddress}api/tracks/{trackId}/file";

    public async Task<bool> DeleteTrackAsync(Guid trackId, CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedRequest(HttpMethod.Delete, $"/api/tracks/{trackId}");
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        return response.IsSuccessStatusCode;
    }

    public async Task<bool> RetryTrackAnalysisAsync(Guid trackId, CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedRequest(HttpMethod.Post, $"/api/tracks/{trackId}/retry-analysis");
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        return response.IsSuccessStatusCode;
    }

    public async Task<(Stream Stream, string ContentType)?> GetTrackAudioStreamAsync(Guid trackId, CancellationToken cancellationToken = default)
    {
        var request = CreateAuthorizedRequest(HttpMethod.Get, $"/api/tracks/{trackId}/file");
        var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (!response.IsSuccessStatusCode) return null;
        
        var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        var contentType = response.Content.Headers.ContentType?.MediaType ?? "audio/mpeg";
        return (stream, contentType);
    }

    // Legacy bytes-only variant kept for internal use
    public async Task<byte[]?> GetTrackAudioBytesAsync(Guid trackId, CancellationToken cancellationToken = default)
    {
        var result = await GetTrackAudioStreamAsync(trackId, cancellationToken);
        if (result == null) return null;
        using var ms = new MemoryStream();
        await result.Value.Stream.CopyToAsync(ms, cancellationToken);
        return ms.ToArray();
    }

    public async Task<RenderMixResponseViewModel> RenderMixFromLibraryAsync(
        Guid trackAId,
        Guid trackBId,
        double? overlayStartSeconds,
        double? rightStartSeconds,
        string? transitionStyle,
        CancellationToken cancellationToken = default)
    {
        var payload = new
        {
            trackAId,
            trackBId,
            overlayStartSeconds,
            rightStartSeconds,
            transitionStyle,
        };
        using var request = CreateAuthorizedJsonRequest(HttpMethod.Post, "/api/mix/render-from-library", payload);
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new InvalidOperationException(ParseBackendError(error));
        }

        // The backend now returns a JSON object (MixRenderResult)
        var result = await response.Content.ReadFromJsonAsync<BackendMixRenderResult>(cancellationToken: cancellationToken);
        if (result == null) throw new InvalidOperationException("Backend returned empty render result.");

        return new RenderMixResponseViewModel
        {
            FileName = result.FileName,
            Base64Audio = Convert.ToBase64String(result.Content),
            Quality = result.Quality != null ? new RenderQualityViewModel
            {
                Score = result.Quality.Score,
                Quality = result.Quality.Quality,
                Summary = result.Quality.Summary,
                Feedback = result.Quality.Feedback,
                Metrics = result.Quality.Metrics
            } : null
        };
    }

    private sealed class BackendMixRenderResult
    {
        public string FileName { get; set; } = string.Empty;
        public byte[] Content { get; set; } = Array.Empty<byte>();
        public BackendQualityResult? Quality { get; set; }
    }

    private sealed class BackendQualityResult
    {
        public int Score { get; set; }
        public string Quality { get; set; } = string.Empty;
        public string Summary { get; set; } = string.Empty;
        public List<string> Feedback { get; set; } = new();
        public Dictionary<string, double> Metrics { get; set; } = new();
    }

    public async Task<IReadOnlyList<string>> GetAvailableSetIdsAsync(CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedRequest(HttpMethod.Get, "/api/ai/sets");
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<List<string>>(cancellationToken) ?? [];
    }

    public async Task<IReadOnlyList<TransitionRecommendationViewModel>> RecommendTransitionsAsync(
        TransitionRecommendationRequestViewModel requestModel,
        CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedJsonRequest(HttpMethod.Post, "/api/ai/recommendations", new
        {
            requestModel.LeftSetId,
            requestModel.RightSetId,
            requestModel.TopK,
        });
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new InvalidOperationException(ParseBackendError(error));
        }

        var payload = await response.Content.ReadAsStringAsync(cancellationToken);
        if (string.IsNullOrWhiteSpace(payload))
        {
            return [];
        }

        var results = JsonSerializer.Deserialize<List<BackendTransitionRecommendation>>(payload, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        }) ?? [];

        return results.Select(item => new TransitionRecommendationViewModel
        {
            LeftSetId = item.LeftSetId,
            LeftSegmentIndex = item.LeftSegmentIndex,
            LeftStartSeconds = item.LeftStartSeconds,
            RightSetId = item.RightSetId,
            RightSegmentIndex = item.RightSegmentIndex,
            RightStartSeconds = item.RightStartSeconds,
            Probability = item.Probability,
        }).ToList();
    }
    
    // --- MIX JOB OPERATIONS ---
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

        using var request = CreateAuthorizedRequest(HttpMethod.Post, "/api/mix-jobs", content);
        using var response = await _httpClient.SendAsync(request, cancellationToken);
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

        using var request = CreateAuthorizedRequest(HttpMethod.Post, "/api/mix/render", content);
        using var response = await _httpClient.SendAsync(request, cancellationToken);

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

        using var request = CreateAuthorizedRequest(HttpMethod.Post, "/api/mix/analyze", content);
        using var response = await _httpClient.SendAsync(request, cancellationToken);
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
        using var request = CreateAuthorizedJsonRequest(HttpMethod.Post, "/api/generate-track", payload);
        using var response = await _httpClient.SendAsync(request, cancellationToken);
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
        using var request = CreateAuthorizedRequest(HttpMethod.Post, url);
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        
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

    private static Task<StreamContent> CreateFileContentAsync(IFormFile file, CancellationToken cancellationToken)
    {
        var content = new StreamContent(file.OpenReadStream());
        content.Headers.ContentType = new(string.IsNullOrEmpty(file.ContentType) ? "application/octet-stream" : file.ContentType);
        return Task.FromResult(content);
    }

    private HttpRequestMessage CreateAuthorizedJsonRequest<TPayload>(HttpMethod method, string uri, TPayload payload)
    {
        var request = CreateAuthorizedRequest(method, uri);
        request.Content = JsonContent.Create(payload);
        return request;
    }

    private HttpRequestMessage CreateAuthorizedRequest(HttpMethod method, string uri, HttpContent? content = null)
    {
        var request = new HttpRequestMessage(method, uri);
        if (content != null)
        {
            request.Content = content;
        }

        var token = _httpContextAccessor.HttpContext?.User.FindFirst("AccessToken")?.Value;
        if (!string.IsNullOrWhiteSpace(token))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        return request;
    }
}
