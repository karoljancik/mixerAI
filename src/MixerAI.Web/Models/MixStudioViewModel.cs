using System.ComponentModel.DataAnnotations;

namespace MixerAI.Web.Models;

public sealed class MixStudioViewModel
{
    public MixStudioViewModel()
    {
        GeneratedTrackStyle = "liquid";
        GeneratedTrackDurationSeconds = 150;
    }

    [Display(Name = "Style")]
    [Required]
    public string GeneratedTrackStyle { get; set; }

    [Display(Name = "Duration")]
    [Range(96, 240)]
    public int GeneratedTrackDurationSeconds { get; set; }

    [Display(Name = "Seed")]
    public int? GeneratedTrackSeed { get; set; }

    public string? ErrorMessage { get; set; }
}
