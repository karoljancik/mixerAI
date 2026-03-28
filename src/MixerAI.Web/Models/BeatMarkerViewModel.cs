namespace MixerAI.Web.Models;

public sealed class BeatMarkerViewModel
{
    public double RelativeSeconds { get; init; }
    public double TimelineSeconds { get; init; }
    public bool IsBar { get; init; }
}
