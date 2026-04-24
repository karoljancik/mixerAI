using MixerAI.Web.Models;

namespace MixerAI.Web.Services;

public interface IMixerBackendClient
{
    Task<bool> RegisterAsync(string email, string password);
    Task<MixerBackendClient.LoginResponse> LoginAsync(string email, string password);
    Task<List<TrackViewModel>> GetTracksAsync(CancellationToken cancellationToken = default);
    Task<TrackViewModel> UploadTrackAsync(IFormFile file, CancellationToken cancellationToken = default);
    Task<bool> DeleteTrackAsync(Guid trackId, CancellationToken cancellationToken = default);
    Task<bool> RetryTrackAnalysisAsync(Guid trackId, CancellationToken cancellationToken = default);
    Task<(Stream Stream, string ContentType)?> GetTrackAudioStreamAsync(Guid trackId, CancellationToken cancellationToken = default);
    Task<byte[]> RenderMixFromLibraryAsync(
        Guid trackAId,
        Guid trackBId,
        double? overlayStartSeconds,
        double? rightStartSeconds,
        CancellationToken cancellationToken = default);
    Task<IReadOnlyList<string>> GetAvailableSetIdsAsync(CancellationToken cancellationToken = default);
    Task<IReadOnlyList<TransitionRecommendationViewModel>> RecommendTransitionsAsync(
        TransitionRecommendationRequestViewModel requestModel,
        CancellationToken cancellationToken = default);
    Task<(byte[] Content, string FileName)> GenerateTrackAsync(
        string style,
        int durationSeconds,
        int? seed,
        CancellationToken cancellationToken);
    Task<(byte[] Content, string FileName)> GenerateMiniMixAsync(
        int? seed,
        CancellationToken cancellationToken);
    Task<MixAnalysisResultViewModel> AnalyzeMixAsync(
        IFormFile trackA,
        IFormFile trackB,
        CancellationToken cancellationToken);
}
