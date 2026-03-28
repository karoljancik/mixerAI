namespace MixerAI.Web.Configuration;

public sealed class BackendApiOptions
{
    public const string SectionName = "BackendApi";

    public string BaseUrl { get; set; } = "http://localhost:5020";
}
