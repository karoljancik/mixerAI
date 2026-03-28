namespace MixerAI.Backend.Models;

public sealed class BeatMarker
{
    public double RelativeSeconds { get; init; }
    public double TimelineSeconds { get; init; }
    public bool IsBar { get; init; }
}
