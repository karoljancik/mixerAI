using MixerAI.Backend.Models;
using MixerAI.Backend.Services;
using MixerAI.Backend.Infrastructure;
using MixerAI.Backend.Data;
using MixerAI.Backend.Entities;
using MixerAI.Backend.Hubs;
using MixerAI.Backend.Workers;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();
builder.Logging.AddConsole();
builder.Logging.AddDebug();

// Medior: Globalne odchytavanie chyb pomocou IExceptionHandler
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();
builder.Services.AddProblemDetails();

builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.WithOrigins("http://localhost:5000")
            .AllowAnyHeader()
            .AllowAnyMethod()
            .AllowCredentials();
    });
});

builder.Services.AddEndpointsApiExplorer();

// --- ZACIATOK AUTENTIFIKACIE A DATABAZY ---
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection") 
                       ?? throw new InvalidOperationException("Connection string 'DefaultConnection' not found.");

builder.Services.AddDbContext<ApplicationDbContext>(options =>
    options.UseNpgsql(connectionString));

// Identity minimal API (Token Bearer / Cookies pre API registráciu a login)
builder.Services.AddAuthorization();
builder.Services.AddAuthentication()
    .AddBearerToken(IdentityConstants.BearerScheme);

builder.Services.AddIdentityCore<ApplicationUser>()
    .AddEntityFrameworkStores<ApplicationDbContext>()
    .AddApiEndpoints();
// --- KONIEC ---

builder.Services.AddScoped<MixJobStore>();
builder.Services.AddScoped<TrackAnalysisService>();
builder.Services.AddSingleton<AiInferenceService>();
builder.Services.AddSingleton<AiMixRenderService>();
builder.Services.AddSingleton<AiDatasetTrackGenerationService>();
builder.Services.AddSingleton<AiMiniMixGenerationService>();

// Medior: Background Queue and SignalR
builder.Services.AddSingleton<IBackgroundTaskQueue>(new BackgroundTaskQueue(100));
builder.Services.AddHostedService<QueuedHostedService>();
builder.Services.AddSignalR();
builder.Services.AddControllers();

var app = builder.Build();

// Auto-migracia databazy pri starte kontajnera
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
    var logger = scope.ServiceProvider.GetRequiredService<ILoggerFactory>().CreateLogger("DatabaseStartup");
    var delay = TimeSpan.FromSeconds(2);

    for (var attempt = 1; attempt <= 10; attempt++)
    {
        try
        {
            logger.LogInformation("Applying EF Core migrations for MixerAI.Backend. Attempt {Attempt}/10.", attempt);
            db.Database.Migrate();
            break;
        }
        catch (Exception exception) when (exception is NpgsqlException or InvalidOperationException)
        {
            if (attempt == 10)
            {
                throw;
            }

            logger.LogWarning(
                exception,
                "Database was not ready for migration attempt {Attempt}. Waiting {DelaySeconds} seconds before retry.",
                attempt,
                delay.TotalSeconds);
            Thread.Sleep(delay);
        }
    }
}

app.UseExceptionHandler();

// Middleware pre overovanie totoznosti pred endpointami
app.UseCors();
app.UseAuthentication();
app.UseAuthorization();

app.MapIdentityApi<ApplicationUser>();
app.MapHub<MixerHub>("/hubs/mixer");
app.MapControllers();

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

// Medior: Endpointy uz nepotrebuju try/catch bloky, odchyti ich obal.
// Teraz pridávame aj RequireAuthorization() aby to volal len prihlaseny user
var apiGroup = app.MapGroup("/api").RequireAuthorization();

apiGroup.MapPost("/mix-jobs", async (MixRequest request, System.Security.Claims.ClaimsPrincipal user, MixJobStore jobStore, CancellationToken cancellationToken) =>
{
    var userId = user.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value;
    if (string.IsNullOrEmpty(userId)) return Results.Unauthorized();

    var job = await jobStore.CreateAsync(request.Title, request.TrackAId, request.TrackBId, userId, cancellationToken);
    return Results.Created($"/api/mix-jobs/{job.Id}", job);
});


apiGroup.MapGet("/mix-jobs", async (System.Security.Claims.ClaimsPrincipal user, MixJobStore jobStore, CancellationToken cancellationToken) =>
{
    var userId = user.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value;
    if (string.IsNullOrEmpty(userId)) return Results.Unauthorized();
    
    var jobs = await jobStore.GetUserJobsAsync(userId, cancellationToken);
    return Results.Ok(jobs);
});

apiGroup.MapGet("/mix-jobs/{id:guid}", async (Guid id, System.Security.Claims.ClaimsPrincipal user, MixJobStore jobStore, CancellationToken cancellationToken) =>
{
    var userId = user.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value;
    if (string.IsNullOrEmpty(userId)) return Results.Unauthorized();

    var job = await jobStore.GetAsync(id, userId, cancellationToken);
    return job is null ? Results.NotFound() : Results.Ok(job);
});

apiGroup.MapPost("/mix/render", async (HttpRequest request, AiMixRenderService renderService, CancellationToken cancellationToken) =>
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

// NEW: Render mix directly from library track IDs (no re-upload needed)
apiGroup.MapPost("/mix/render-from-library", async (
    RenderFromLibraryRequest request,
    System.Security.Claims.ClaimsPrincipal user,
    MixerAI.Backend.Data.ApplicationDbContext db,
    AiMixRenderService renderService,
    IHostEnvironment env,
    CancellationToken cancellationToken) =>
{
    var userId = user.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value;
    if (string.IsNullOrEmpty(userId)) return Results.Unauthorized();

    var trackA = await db.Tracks.FirstOrDefaultAsync(t => t.Id == request.TrackAId && t.UserId == userId, cancellationToken);
    var trackB = await db.Tracks.FirstOrDefaultAsync(t => t.Id == request.TrackBId && t.UserId == userId, cancellationToken);

    if (trackA == null || trackB == null) return Results.NotFound("One or both tracks were not found.");
    var uploadPath = Path.Combine(env.ContentRootPath, "App_Data", "UserTracks");
    
    var trackAActualPath = TrackStoragePathResolver.ResolvePhysicalPath(uploadPath, trackA.FilePath);
    var trackBActualPath = TrackStoragePathResolver.ResolvePhysicalPath(uploadPath, trackB.FilePath);

    if (!System.IO.File.Exists(trackAActualPath) || !System.IO.File.Exists(trackBActualPath))
        return Results.Problem("Track audio files are missing from storage.");

    // Wrap physical files as IFormFile-compatible streams
    var fileA = new PhysicalFileFormFile(trackAActualPath, trackA.Title);
    var fileB = new PhysicalFileFormFile(trackBActualPath, trackB.Title);

    var result = await renderService.RenderAsync(
        fileA,
        fileB,
        new MixRenderOptions
        {
            OverlayStartSeconds = request.OverlayStartSeconds,
            RightStartSeconds = request.RightStartSeconds,
        },
        cancellationToken);
    return Results.File(result.Content, "audio/mpeg", result.FileName);
});


apiGroup.MapPost("/mix/analyze", async (HttpRequest request, AiMixRenderService renderService, CancellationToken cancellationToken) =>
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

apiGroup.MapGet("/ai/sets", (AiInferenceService inferenceService) =>
{
    return Results.Ok(inferenceService.GetAvailableSetIds());
});

apiGroup.MapPost("/ai/recommendations", async (TransitionRecommendationRequest request, AiInferenceService inferenceService, CancellationToken cancellationToken) =>
{
    if (string.IsNullOrWhiteSpace(request.LeftSetId) || string.IsNullOrWhiteSpace(request.RightSetId))
        throw new BadHttpRequestException("Both LeftSetId and RightSetId are required.");

    var recommendations = await inferenceService.RecommendAsync(request, cancellationToken);
    return Results.Ok(recommendations);
});

apiGroup.MapPost("/generate-track", async (GenerateDatasetTrackRequest request, AiDatasetTrackGenerationService generationService, CancellationToken cancellationToken) =>
{
    var result = await generationService.GenerateAsync(request, cancellationToken);
    return Results.File(result.Content, "audio/mpeg", result.FileName);
});

apiGroup.MapPost("/generate-mini-mix", async ([Microsoft.AspNetCore.Mvc.FromQuery] int? seed, AiMiniMixGenerationService generationService, CancellationToken cancellationToken) =>
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

public record RenderFromLibraryRequest(
    Guid TrackAId,
    Guid TrackBId,
    double? OverlayStartSeconds,
    double? RightStartSeconds);

// Adapter: wraps a physical file on disk as IFormFile for AiMixRenderService
public sealed class PhysicalFileFormFile : IFormFile
{
    private readonly string _path;
    public PhysicalFileFormFile(string path, string displayName)
    {
        _path = path;
        var extension = Path.GetExtension(path);
        FileName = string.IsNullOrWhiteSpace(extension) ? displayName : $"{displayName}{extension}";
        Name = "file";
        ContentType = extension.ToLowerInvariant() switch
        {
            ".mp4" or ".m4a" => "audio/mp4",
            ".wav" => "audio/wav",
            ".ogg" => "audio/ogg",
            ".flac" => "audio/flac",
            ".aiff" => "audio/aiff",
            _ => "audio/mpeg",
        };
        Length = new FileInfo(path).Length;
        ContentDisposition = $"form-data; name=\"file\"; filename=\"{FileName}\"";
        Headers = new HeaderDictionary();
    }
    public string ContentType { get; }
    public string ContentDisposition { get; }
    public IHeaderDictionary Headers { get; }
    public long Length { get; }
    public string Name { get; }
    public string FileName { get; }
    public Stream OpenReadStream() => System.IO.File.OpenRead(_path);
    public void CopyTo(Stream target) { using var s = OpenReadStream(); s.CopyTo(target); }
    public async Task CopyToAsync(Stream target, CancellationToken ct = default) { await using var s = OpenReadStream(); await s.CopyToAsync(target, ct); }
}

public partial class Program;
