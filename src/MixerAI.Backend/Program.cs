using MixerAI.Backend.Models;
using MixerAI.Backend.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();
builder.Logging.AddConsole();
builder.Logging.AddDebug();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSingleton<MixJobStore>();
builder.Services.AddSingleton<AiInferenceService>();
builder.Services.AddSingleton<AiMixRenderService>();
builder.Services.AddSingleton<AiDatasetTrackGenerationService>();
builder.Services.AddSingleton<AiMiniMixGenerationService>();

var app = builder.Build();

app.MapGet("/", () => Results.Ok(new
{
    app = "MixerAI.Backend",
    status = "running",
    utc = DateTime.UtcNow
}));

app.MapGet("/api/health", () => Results.Ok(new
{
    status = "healthy",
    utc = DateTime.UtcNow
}));

app.MapPost("/api/mix-jobs", async (HttpRequest request, MixJobStore jobStore, CancellationToken cancellationToken) =>
{
    try
    {
        if (!request.HasFormContentType)
        {
            return Results.BadRequest(new { error = "Expected multipart form data." });
        }

        var form = await request.ReadFormAsync(cancellationToken);
        var trackA = form.Files["trackA"];
        var trackB = form.Files["trackB"];

        if (trackA is null || trackB is null)
        {
            return Results.BadRequest(new { error = "Both trackA and trackB are required." });
        }

        var title = form["title"].ToString();
        var job = await jobStore.CreateAsync(title, trackA, trackB, cancellationToken);

        return Results.Created($"/api/mix-jobs/{job.Id}", job);
    }
    catch (BadHttpRequestException exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
});

app.MapGet("/api/mix-jobs/{id:guid}", (Guid id, MixJobStore jobStore) =>
{
    var job = jobStore.Get(id);
    return job is null ? Results.NotFound() : Results.Ok(job);
});

app.MapPost("/api/mix/render", async (HttpRequest request, AiMixRenderService renderService, CancellationToken cancellationToken) =>
{
    try
    {
        if (!request.HasFormContentType)
        {
            return Results.BadRequest(new { error = "Expected multipart form data." });
        }

        var form = await request.ReadFormAsync(cancellationToken);
        var trackA = form.Files["trackA"];
        var trackB = form.Files["trackB"];

        if (trackA is null || trackB is null)
        {
            return Results.BadRequest(new { error = "Both trackA and trackB are required." });
        }

        var options = new MixRenderOptions
        {
            OverlayStartSeconds = TryReadDouble(form["overlayStartSeconds"]),
            RightStartSeconds = TryReadDouble(form["rightStartSeconds"]),
        };

        var result = await renderService.RenderAsync(trackA, trackB, options, cancellationToken);
        return Results.File(result.Content, "audio/mpeg", result.FileName);
    }
    catch (BadHttpRequestException exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
    catch (Exception exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
});

app.MapPost("/api/mix/analyze", async (HttpRequest request, AiMixRenderService renderService, CancellationToken cancellationToken) =>
{
    try
    {
        if (!request.HasFormContentType)
        {
            return Results.BadRequest(new { error = "Expected multipart form data." });
        }

        var form = await request.ReadFormAsync(cancellationToken);
        var trackA = form.Files["trackA"];
        var trackB = form.Files["trackB"];

        if (trackA is null || trackB is null)
        {
            return Results.BadRequest(new { error = "Both trackA and trackB are required." });
        }

        var analysis = await renderService.AnalyzeAsync(trackA, trackB, cancellationToken);
        return Results.Ok(analysis);
    }
    catch (BadHttpRequestException exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
    catch (Exception exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
});

app.MapGet("/api/ai/sets", (AiInferenceService inferenceService) =>
{
    return Results.Ok(inferenceService.GetAvailableSetIds());
});

app.MapPost("/api/ai/recommendations", async (
    TransitionRecommendationRequest request,
    AiInferenceService inferenceService,
    CancellationToken cancellationToken) =>
{
    if (string.IsNullOrWhiteSpace(request.LeftSetId) || string.IsNullOrWhiteSpace(request.RightSetId))
    {
        return Results.BadRequest(new { error = "Both LeftSetId and RightSetId are required." });
    }

    try
    {
        var recommendations = await inferenceService.RecommendAsync(request, cancellationToken);
        return Results.Ok(recommendations);
    }
    catch (Exception exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
});

app.MapPost("/api/generate-track", async (
    GenerateDatasetTrackRequest request,
    AiDatasetTrackGenerationService generationService,
    CancellationToken cancellationToken) =>
{
    try
    {
        var result = await generationService.GenerateAsync(request, cancellationToken);
        return Results.File(result.Content, "audio/mpeg", result.FileName);
    }
    catch (Exception exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
});

app.MapPost("/api/generate-mini-mix", async (
    [Microsoft.AspNetCore.Mvc.FromQuery] int? seed,
    AiMiniMixGenerationService generationService,
    CancellationToken cancellationToken) =>
{
    try
    {
        var result = await generationService.GenerateMiniMixAsync(seed, cancellationToken);
        return Results.File(result.Content, "audio/mpeg", result.FileName);
    }
    catch (Exception exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }
});

app.Run();

static double? TryReadDouble(string? value)
{
    if (string.IsNullOrWhiteSpace(value))
    {
        return null;
    }

    return double.TryParse(value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var parsed)
        ? parsed
        : null;
}
