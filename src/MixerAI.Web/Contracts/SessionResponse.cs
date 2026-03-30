namespace MixerAI.Web.Contracts;

public sealed class SessionResponse
{
    public bool IsAuthenticated { get; init; }
    public string? DisplayName { get; init; }
    public string? Email { get; init; }
}
