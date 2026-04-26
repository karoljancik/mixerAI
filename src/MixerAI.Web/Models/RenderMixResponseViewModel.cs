
namespace MixerAI.Web.Models;

public sealed class RenderQualityViewModel
{
    public int Score { get; init; }
    public string Quality { get; init; } = string.Empty;
    public string Summary { get; init; } = string.Empty;
    public List<string> Feedback { get; init; } = new();
    public Dictionary<string, double> Metrics { get; init; } = new();
}

public sealed class RenderMixResponseViewModel
{
    public string FileName { get; init; } = string.Empty;
    public string Base64Audio { get; init; } = string.Empty;
    public RenderQualityViewModel? Quality { get; init; }
}
