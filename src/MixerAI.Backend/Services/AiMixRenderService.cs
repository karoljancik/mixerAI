using System.Diagnostics;
using System.Text.Json;
using MixerAI.Backend.Models;

namespace MixerAI.Backend.Services;

public sealed class AiMixRenderService
{
    private readonly string _repoRoot;
    private readonly string _modelPath;
    private readonly string _pythonExecutable;
    private readonly string _rendersRoot;

    public AiMixRenderService(IHostEnvironment environment)
    {
        _repoRoot = Path.GetFullPath(Path.Combine(environment.ContentRootPath, "..", ".."));
        _modelPath = Path.Combine(_repoRoot, "data", "training", "transition_scorer.pt");
        _pythonExecutable = "python";
        _rendersRoot = Path.Combine(environment.ContentRootPath, "App_Data", "RenderedMixes");
        Directory.CreateDirectory(_rendersRoot);
    }

    public async Task<MixRenderResult> RenderAsync(
        IFormFile trackA,
        IFormFile trackB,
        MixRenderOptions? options,
        CancellationToken cancellationToken)
    {
        ValidateFile(trackA, "trackA");
        ValidateFile(trackB, "trackB");

        var renderId = Guid.NewGuid().ToString("N");
        var workingDirectory = Path.Combine(_rendersRoot, renderId);
        Directory.CreateDirectory(workingDirectory);

        var trackAPath = Path.Combine(workingDirectory, $"track-a{Path.GetExtension(trackA.FileName)}");
        var trackBPath = Path.Combine(workingDirectory, $"track-b{Path.GetExtension(trackB.FileName)}");
        var outputPath = Path.Combine(workingDirectory, "mixed-output.mp3");

        await SaveAsync(trackA, trackAPath, cancellationToken);
        await SaveAsync(trackB, trackBPath, cancellationToken);

        // Use trained AI model if available, otherwise fallback to simple crossfade
        var scriptPath = File.Exists(_modelPath) ? "ai/render_mix.py" : "ai/simple_crossfade_mix.py";

        var processStartInfo = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = _repoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        processStartInfo.ArgumentList.Add(scriptPath);
        processStartInfo.ArgumentList.Add("--track-a");
        processStartInfo.ArgumentList.Add(trackAPath);
        processStartInfo.ArgumentList.Add("--track-b");
        processStartInfo.ArgumentList.Add(trackBPath);
        processStartInfo.ArgumentList.Add("--output-path");
        processStartInfo.ArgumentList.Add(outputPath);

        if (File.Exists(_modelPath))
        {
            processStartInfo.ArgumentList.Add("--model-path");
            processStartInfo.ArgumentList.Add(_modelPath);
            AppendRenderOptions(processStartInfo, options);
        }

        using var process = Process.Start(processStartInfo)
            ?? throw new InvalidOperationException("Failed to start AI mix render process.");

        await process.WaitForExitAsync(cancellationToken);
        if (process.ExitCode != 0)
        {
            var error = await process.StandardError.ReadToEndAsync(cancellationToken);
            if (string.IsNullOrWhiteSpace(error))
            {
                error = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            }

            throw new InvalidOperationException($"AI mix render failed: {SummarizeError(error)}");
        }

        if (!File.Exists(outputPath))
        {
            throw new InvalidOperationException("AI mix render did not produce an MP3 output.");
        }

        return new MixRenderResult
        {
            FileName = $"mixerai-mix-{renderId}.mp3",
            Content = await File.ReadAllBytesAsync(outputPath, cancellationToken),
        };
    }


    public async Task<MixAnalysisResult> AnalyzeAsync(
        IFormFile trackA,
        IFormFile trackB,
        CancellationToken cancellationToken)
    {
        ValidateFile(trackA, "trackA");
        ValidateFile(trackB, "trackB");

        if (!File.Exists(_modelPath))
        {
            throw new InvalidOperationException("Trained AI model checkpoint was not found.");
        }

        var renderId = Guid.NewGuid().ToString("N");
        var workingDirectory = Path.Combine(_rendersRoot, renderId);
        Directory.CreateDirectory(workingDirectory);

        var trackAPath = Path.Combine(workingDirectory, $"track-a{Path.GetExtension(trackA.FileName)}");
        var trackBPath = Path.Combine(workingDirectory, $"track-b{Path.GetExtension(trackB.FileName)}");
        var analysisPath = Path.Combine(workingDirectory, "analysis-output.json");

        await SaveAsync(trackA, trackAPath, cancellationToken);
        await SaveAsync(trackB, trackBPath, cancellationToken);

        var processStartInfo = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = _repoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        processStartInfo.ArgumentList.Add("ai/analyze_mix.py");
        processStartInfo.ArgumentList.Add("--track-a");
        processStartInfo.ArgumentList.Add(trackAPath);
        processStartInfo.ArgumentList.Add("--track-b");
        processStartInfo.ArgumentList.Add(trackBPath);
        processStartInfo.ArgumentList.Add("--model-path");
        processStartInfo.ArgumentList.Add(_modelPath);
        processStartInfo.ArgumentList.Add("--output-path");
        processStartInfo.ArgumentList.Add(analysisPath);

        using var process = Process.Start(processStartInfo)
            ?? throw new InvalidOperationException("Failed to start AI mix analysis process.");

        await process.WaitForExitAsync(cancellationToken);
        if (process.ExitCode != 0)
        {
            var error = await process.StandardError.ReadToEndAsync(cancellationToken);
            if (string.IsNullOrWhiteSpace(error))
            {
                error = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            }

            throw new InvalidOperationException($"AI mix analysis failed: {SummarizeError(error)}");
        }

        if (!File.Exists(analysisPath))
        {
            throw new InvalidOperationException("AI mix analysis did not produce preview data.");
        }

        var json = await File.ReadAllTextAsync(analysisPath, cancellationToken);
        var result = JsonSerializer.Deserialize<MixAnalysisResult>(
            json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        return result ?? throw new InvalidOperationException("AI mix analysis returned empty preview data.");
    }

    private static void ValidateFile(IFormFile file, string fieldName)
    {
        var extension = Path.GetExtension(file.FileName);
        var allowedExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            ".mp3",
            ".wav",
            ".flac",
            ".aiff",
            ".mp4",
            ".m4a",
            ".ogg"
        };

        if (file.Length == 0)
        {
            throw new BadHttpRequestException($"{fieldName} is empty.");
        }

        if (!allowedExtensions.Contains(extension))
        {
            throw new BadHttpRequestException($"{fieldName} has unsupported format.");
        }
    }

    private static async Task SaveAsync(IFormFile file, string destinationPath, CancellationToken cancellationToken)
    {
        await using var targetStream = File.Create(destinationPath);
        await using var sourceStream = file.OpenReadStream();
        await sourceStream.CopyToAsync(targetStream, cancellationToken);
    }

    private static string SummarizeError(string error)
    {
        if (string.IsNullOrWhiteSpace(error))
        {
            return "Unknown render error.";
        }

        var lines = error
            .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Trim())
            .Where(line => !string.IsNullOrWhiteSpace(line))
            .ToArray();

        var normalized = lines.LastOrDefault(line =>
                !line.StartsWith("Traceback", StringComparison.OrdinalIgnoreCase)
                && !line.StartsWith("File ", StringComparison.Ordinal))
            ?? lines.LastOrDefault()
            ?? error.Trim();

        if (normalized.Length > 320)
        {
            normalized = normalized[..320] + "...";
        }

        return normalized;
    }

    private static void AppendRenderOptions(ProcessStartInfo processStartInfo, MixRenderOptions? options)
    {
        if (options?.OverlayStartSeconds is double overlayStartSeconds && overlayStartSeconds >= 0)
        {
            processStartInfo.ArgumentList.Add("--overlay-start-seconds");
            processStartInfo.ArgumentList.Add(overlayStartSeconds.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture));
        }

        if (options?.RightStartSeconds is double rightStartSeconds && rightStartSeconds >= 0)
        {
            processStartInfo.ArgumentList.Add("--right-start-seconds");
            processStartInfo.ArgumentList.Add(rightStartSeconds.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture));
        }
    }
}
