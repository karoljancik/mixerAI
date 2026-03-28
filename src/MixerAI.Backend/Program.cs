using MixerAI.Backend.Models;
using MixerAI.Backend.Services;
using MixerAI.Backend.Infrastructure;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();
builder.Logging.AddConsole();
builder.Logging.AddDebug();

// Medior: Globalne odchytavanie chyb pomocou IExceptionHandler
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();
builder.Services.AddProblemDetails();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSingleton<MixJobStore>();
builder.Services.AddSingleton<AiInferenceService>();
builder.Services.AddSingleton<AiMixRenderService>();
builder.Services.AddSingleton<AiDatasetTrackGenerationService>();
builder.Services.AddSingleton<AiMiniMixGenerationService>();

var app = builder.Build();

// Medior: Aplikovanie Global Exception Handlera
app.UseExceptionHandler();

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

// Medior: Endpointy uz nepotrebuju try/catch bloky
app.MapPost("/api/mix-jobs", async (HttpRequest request, MixJobStore jobStore, CancellationToken cancellationToken) =>
{
    if (!request.HasFormContentType)
        throw new BadHttpRequestException("Expected multipart form data.");

    var form = await request.ReadFormAsync(cancellationToken);
    var trackA = form.Files["trackA"];
    var trackB = form.Files["trackB"];

    if (trackA is null || trackB is null)
        throw new BadHttpRequestException("Both trackA and trackB are required.");

    var title = form["title"].ToString();
    var job = await jobStore.CreateAsync(title, trackA, trackB, cancellationToken);

    return Results.Created($"/api/mix-jobs/{job.Id}", job);
});

app.MapGet("/api/mix-jobs/{id:guid}", (Guid id, MixJobStore jobStore) =>
{
    var job = jobStore.Get(id);
    return job is null ? Results.NotFound() : Results.Ok(job);
});

app.MapPost("/api/mix/render", async (HttpRequest request, AiMixRenderService renderService, CancellationToken cancellationToken) =>
{
    if (!request.HasFormContentType)
        throw new BadHttpRequestException("Expected multipart form data.");

    var form = await request.ReadFormAsync(cancellationToken);
    var trackA = form.Files["trackA"];
    var trackB = form.Files["trackB"];

    if (trackA is null || trackB is null)
        throw new BadHttpRequestException("Both trackA and trackB are required.");

    var options = new MixRenderOptions
    {
        OverlayStartSeconds = TryReadDouble(form["overlayStartSeconds"]),
        RightStartSeconds = TryReadDouble(form["rightStartSeconds"]),
    };

    var result = await renderService.RenderAsync(trackA, trackB, options, cancellationToken);
    return Results.File(result.Content, "audio/mpeg", result.FileName);
});

app.MapPost("/api/mix/analyze", async (HttpRequest request, AiMixRenderService renderService, CancellationToken cancellationToken) =>
{
    if (!request.HasFormContentType)
        throw new BadHttpRequestException("Expected multipart form data.");

    var form = await request.ReadFormAsync(cancellationToken);
    var trackA = form.Files["trackA"];
    var trackB = form.Files["trackB"];

    if (trackA is null || trackB is null)
        throw new BadHttpRequestException("Both trackA and trackB are required.");

    var analysis = await renderService.AnalyzeAsync(trackA, trackB, cancellationToken);
    return Results.Ok(analysis);
});

app.MapGet("/api/ai/sets", (AiInferenceService inferenceService) =>
{
    return Results.Ok(inferenceService.GetAvailableSetIds());
});

app.MapPost("/api/ai/recommendations", async (TransitionRecommendationRequest request, AiInferenceService inferenceService, CancellationToken cancellationToken) =>
{
    if (string.IsNullOrWhiteSpace(request.LeftSetId) || string.IsNullOrWhiteSpace(request.RightSetId))
        throw new BadHttpRequestException("Both LeftSetId and RightSetId are required.");

    var recommendations = await inferenceService.RecommendAsync(request, cancellationToken);
    return Results.Ok(recommendations);
});

app.MapPost("/api/generate-track", async (GenerateDatasetTrackRequest request, AiDatasetTrackGenerationService generationService, CancellationToken cancellationToken) =>
{
    var result = await generationService.GenerateAsync(request, cancellationToken);
    return Results.File(result.Content, "audio/mpeg", result.FileName);
});

app.MapPost("/api/generate-mini-mix", async ([Microsoft.AspNetCore.Mvc.FromQuery] int? seed, AiMiniMixGenerationService generationService, CancellationToken cancellationToken) =>
{
    var result = await generationService.GenerateMiniMixAsync(seed, cancellationToken);
    return Results.File(result.Content, "audio/mpeg", result.FileName);
});

app.Run();

static double? TryReadDouble(string? value)
{
    if (string.IsNullOrWhiteSpace(value)) return null;
    return double.TryParse(value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var parsed) ? parsed : null;
}
