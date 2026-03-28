namespace MixerAI.Backend.Entities;

public class MixJob
{
    public Guid Id { get; set; }
    
    // Názov mixu od usera
    public string Title { get; set; } = string.Empty;
    
    public string Status { get; set; } = "Created";
    public DateTime CreatedAtUtc { get; set; }
    public DateTime? CompletedAtUtc { get; set; }
    
    // IDs of tracks from library
    public Guid TrackAId { get; set; }
    public Track TrackA { get; set; } = null!;

    public Guid TrackBId { get; set; }
    public Track TrackB { get; set; } = null!;
    
    // Physical result storage
    public string? ResultFilePath { get; set; }
    
    // Prepojenie na usera
    public string UserId { get; set; } = string.Empty;
    public ApplicationUser User { get; set; } = null!;
}
