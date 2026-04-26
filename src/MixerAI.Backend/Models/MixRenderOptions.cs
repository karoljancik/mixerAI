namespace MixerAI.Backend.Models;

public sealed class MixRenderOptions
{
    public double? OverlayStartSeconds { get; init; }
    public double? RightStartSeconds { get; init; }
    public string? TransitionStyle { get; init; }
}
