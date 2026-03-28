namespace MixerAI.Web.Models;

public sealed class MixTrackPreviewViewModel
{
    public string Label { get; init; } = string.Empty;
    public double DurationSeconds { get; init; }
    public double PreviewStartSeconds { get; init; }
    public double PreviewDurationSeconds { get; init; }
    public double Bpm { get; init; }
    public double BeatPeriodSeconds { get; init; }
    public double TimelineOffsetSeconds { get; init; }
    public IReadOnlyList<double> Waveform { get; init; } = [];
    public IReadOnlyList<BeatMarkerViewModel> BeatMarkers { get; init; } = [];
}
