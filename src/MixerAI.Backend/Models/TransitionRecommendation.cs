using System.Text.Json.Serialization;

namespace MixerAI.Backend.Models;

public sealed class TransitionRecommendation
{
    [JsonPropertyName("left_set_id")]
    public string LeftSetId { get; init; } = string.Empty;

    [JsonPropertyName("left_segment_index")]
    public int LeftSegmentIndex { get; init; }

    [JsonPropertyName("left_start_seconds")]
    public double LeftStartSeconds { get; init; }

    [JsonPropertyName("right_set_id")]
    public string RightSetId { get; init; } = string.Empty;

    [JsonPropertyName("right_segment_index")]
    public int RightSegmentIndex { get; init; }

    [JsonPropertyName("right_start_seconds")]
    public double RightStartSeconds { get; init; }

    [JsonPropertyName("probability")]
    public double Probability { get; init; }
}
