namespace MixerAI.Backend.Models;

public sealed class MixRenderResult
{
    public string FileName { get; init; } = string.Empty;
    public byte[] Content { get; init; } = [];
}
