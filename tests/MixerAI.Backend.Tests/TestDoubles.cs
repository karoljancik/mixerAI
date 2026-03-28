using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc.ViewFeatures;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using MixerAI.Backend.Infrastructure;
using MixerAI.Web.Models;
using MixerAI.Web.Services;

namespace MixerAI.Backend.Tests;

internal sealed class FakeBackgroundTaskQueue : IBackgroundTaskQueue
{
    public List<Func<IServiceProvider, CancellationToken, ValueTask>> WorkItems { get; } = [];

    public ValueTask QueueBackgroundWorkItemAsync(Func<IServiceProvider, CancellationToken, ValueTask> workItem)
    {
        WorkItems.Add(workItem);
        return ValueTask.CompletedTask;
    }

    public ValueTask<Func<IServiceProvider, CancellationToken, ValueTask>> DequeueAsync(CancellationToken cancellationToken)
    {
        throw new NotSupportedException();
    }
}

internal sealed class TestHostEnvironment : IHostEnvironment
{
    public string EnvironmentName { get; set; } = Environments.Development;
    public string ApplicationName { get; set; } = "MixerAI.Tests";
    public string ContentRootPath { get; set; } = Path.Combine(Path.GetTempPath(), $"mixerai-tests-{Guid.NewGuid():N}");
    public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
}

internal sealed class FakeMixerBackendClient : IMixerBackendClient
{
    public List<TrackViewModel> Tracks { get; set; } = [];
    public IReadOnlyList<string> SetIds { get; set; } = [];
    public IReadOnlyList<TransitionRecommendationViewModel> Recommendations { get; set; } = [];
    public bool DeleteTrackResult { get; set; } = true;
    public bool RetryTrackAnalysisResult { get; set; } = true;
    public bool RegisterResult { get; set; } = true;
    public MixerBackendClient.LoginResponse LoginResult { get; set; } = new(false);
    public byte[] RenderedMix { get; set; } = [1, 2, 3];
    public (byte[] Content, string FileName) GeneratedTrack { get; set; } = ([4, 5, 6], "generated.mp3");
    public (byte[] Content, string FileName) GeneratedMiniMix { get; set; } = ([7, 8, 9], "minimix.mp3");
    public int UploadCalls { get; private set; }
    public int GenerateTrackCalls { get; private set; }

    public Task<bool> RegisterAsync(string email, string password) => Task.FromResult(RegisterResult);

    public Task<MixerBackendClient.LoginResponse> LoginAsync(string email, string password) => Task.FromResult(LoginResult);

    public Task<List<TrackViewModel>> GetTracksAsync(CancellationToken cancellationToken = default) => Task.FromResult(Tracks);

    public Task<TrackViewModel> UploadTrackAsync(IFormFile file, CancellationToken cancellationToken = default)
    {
        UploadCalls += 1;
        return Task.FromResult(new TrackViewModel
        {
            Id = Guid.NewGuid(),
            Title = file.FileName,
            Status = "Pending"
        });
    }

    public Task<bool> DeleteTrackAsync(Guid trackId, CancellationToken cancellationToken = default) => Task.FromResult(DeleteTrackResult);

    public Task<bool> RetryTrackAnalysisAsync(Guid trackId, CancellationToken cancellationToken = default) => Task.FromResult(RetryTrackAnalysisResult);

    public Task<(Stream Stream, string ContentType)?> GetTrackAudioStreamAsync(Guid trackId, CancellationToken cancellationToken = default)
    {
        return Task.FromResult< (Stream Stream, string ContentType)? >((new MemoryStream([1, 2, 3]), "audio/mpeg"));
    }

    public Task<byte[]> RenderMixFromLibraryAsync(Guid trackAId, Guid trackBId, CancellationToken cancellationToken = default)
        => Task.FromResult(RenderedMix);

    public Task<IReadOnlyList<string>> GetAvailableSetIdsAsync(CancellationToken cancellationToken = default)
        => Task.FromResult(SetIds);

    public Task<IReadOnlyList<TransitionRecommendationViewModel>> RecommendTransitionsAsync(
        TransitionRecommendationRequestViewModel requestModel,
        CancellationToken cancellationToken = default)
        => Task.FromResult(Recommendations);

    public Task<(byte[] Content, string FileName)> GenerateTrackAsync(
        string style,
        int durationSeconds,
        int? seed,
        CancellationToken cancellationToken)
    {
        GenerateTrackCalls += 1;
        return Task.FromResult(GeneratedTrack);
    }

    public Task<(byte[] Content, string FileName)> GenerateMiniMixAsync(int? seed, CancellationToken cancellationToken)
        => Task.FromResult(GeneratedMiniMix);
}

internal sealed class TestTempDataProvider : ITempDataProvider
{
    private readonly Dictionary<string, object> _store = [];

    public IDictionary<string, object> LoadTempData(HttpContext context) => new Dictionary<string, object>(_store);

    public void SaveTempData(HttpContext context, IDictionary<string, object> values)
    {
        _store.Clear();
        foreach (var pair in values)
        {
            _store[pair.Key] = pair.Value;
        }
    }
}

internal sealed class FakeAuthenticationService : IAuthenticationService
{
    public ClaimsPrincipal? SignedInPrincipal { get; private set; }

    public Task<AuthenticateResult> AuthenticateAsync(HttpContext context, string? scheme)
        => Task.FromResult(AuthenticateResult.NoResult());

    public Task ChallengeAsync(HttpContext context, string? scheme, AuthenticationProperties? properties)
        => Task.CompletedTask;

    public Task ForbidAsync(HttpContext context, string? scheme, AuthenticationProperties? properties)
        => Task.CompletedTask;

    public Task SignInAsync(HttpContext context, string? scheme, ClaimsPrincipal principal, AuthenticationProperties? properties)
    {
        SignedInPrincipal = principal;
        return Task.CompletedTask;
    }

    public Task SignOutAsync(HttpContext context, string? scheme, AuthenticationProperties? properties)
        => Task.CompletedTask;
}

internal static class TestHelpers
{
    public static DefaultHttpContext CreateHttpContext(params Claim[] claims)
    {
        var context = new DefaultHttpContext();
        context.User = new ClaimsPrincipal(new ClaimsIdentity(claims, "Test"));
        return context;
    }

    public static TempDataDictionary CreateTempData(HttpContext context)
        => new(context, new TestTempDataProvider());

    public static string CreateUnsignedJwt(string subject, string email, string name)
    {
        static string Encode(object payload)
        {
            var json = System.Text.Json.JsonSerializer.Serialize(payload);
            var bytes = System.Text.Encoding.UTF8.GetBytes(json);
            return Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        }

        return $"{Encode(new { alg = "none", typ = "JWT" })}.{Encode(new { sub = subject, email, unique_name = name })}.signature";
    }

    public static ServiceProvider BuildAuthServiceProvider(FakeAuthenticationService authService)
    {
        var services = new ServiceCollection();
        services.AddSingleton<IAuthenticationService>(authService);
        return services.BuildServiceProvider();
    }
}
