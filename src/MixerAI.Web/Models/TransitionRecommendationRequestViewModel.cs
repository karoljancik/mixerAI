using System.ComponentModel.DataAnnotations;

namespace MixerAI.Web.Models;

public sealed class TransitionRecommendationRequestViewModel
{
    [Display(Name = "Left set")]
    [Required]
    public string LeftSetId { get; set; } = string.Empty;

    [Display(Name = "Right set")]
    [Required]
    public string RightSetId { get; set; } = string.Empty;

    [Display(Name = "Top candidates")]
    [Range(1, 20)]
    public int TopK { get; set; } = 5;
}
