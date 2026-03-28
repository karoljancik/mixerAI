using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace MixerAI.Backend.Entities;

public class Track
{
    public Guid Id { get; set; }
    
    [Required]
    public string Title { get; set; } = string.Empty;
    
    public string? Artist { get; set; }
    
    public double? BPM { get; set; }
    
    public string? CamelotKey { get; set; }
    
    public double DurationSeconds { get; set; }
    
    // Path to the actual audio file on disk/storage
    public string FilePath { get; set; } = string.Empty;
    
    // JSON spectrum data for fast waveform rendering
    public string? WaveformDataJson { get; set; }
    
    public string Status { get; set; } = "Pending"; // Pending, Analyzing, Ready, Error
    
    public DateTime CreatedAtUtc { get; set; } = DateTime.UtcNow;
    
    [Required]
    public string UserId { get; set; } = string.Empty;
    public ApplicationUser User { get; set; } = null!;
}
