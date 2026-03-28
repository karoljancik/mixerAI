namespace MixerAI.Backend.Models;

public sealed class TransitionRecommendation
{
    public string LeftSetId { get; init; } = string.Empty;
    public int LeftSegmentIndex { get; init; }
    public double LeftStartSeconds { get; init; }
    public string RightSetId { get; init; } = string.Empty;
    public int RightSegmentIndex { get; init; }
    public double RightStartSeconds { get; init; }
    public double Probability { get; init; }
}
