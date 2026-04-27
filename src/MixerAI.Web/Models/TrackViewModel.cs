namespace MixerAI.Web.Models;

public class TrackViewModel
{
    public Guid Id { get; set; }
    public string Title { get; set; } = string.Empty;
    public string? Artist { get; set; }
    public double? BPM { get; set; }
    public double? BeatOffset { get; set; }
    public string? CamelotKey { get; set; }
    public double DurationSeconds { get; set; }
    public string? WaveformDataJson { get; set; }
    public string Status { get; set; } = string.Empty;
    public int AnalysisAttempts { get; set; }
    public string? LastAnalysisError { get; set; }
    public DateTime? LastAnalysisStartedAtUtc { get; set; }
    public DateTime? LastAnalysisCompletedAtUtc { get; set; }
    public DateTime CreatedAtUtc { get; set; }
}
