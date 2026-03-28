using System.Diagnostics;
using System.Text.Json;
using MixerAI.Backend.Models;

namespace MixerAI.Backend.Services;

public sealed class AiInferenceService
{
    private readonly string _repoRoot;
    private readonly string _featuresDir;
    private readonly string _modelPath;
    private readonly string _pythonExecutable;

    public AiInferenceService(IHostEnvironment environment)
    {
        _repoRoot = Path.GetFullPath(Path.Combine(environment.ContentRootPath, "..", ".."));
        _featuresDir = Path.Combine(_repoRoot, "data", "features");
        _modelPath = Path.Combine(_repoRoot, "data", "training", "transition_scorer.pt");
        _pythonExecutable = "python";
    }

    public IReadOnlyList<string> GetAvailableSetIds()
    {
        if (!Directory.Exists(_featuresDir))
        {
            return [];
        }

        return Directory.EnumerateFiles(_featuresDir, "*.features.json")
            .Select(Path.GetFileNameWithoutExtension)
            .Select(fileName => fileName?.Replace(".features", string.Empty, StringComparison.OrdinalIgnoreCase) ?? string.Empty)
            .Where(fileName => !string.IsNullOrWhiteSpace(fileName))
            .OrderBy(fileName => fileName, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public async Task<IReadOnlyList<TransitionRecommendation>> RecommendAsync(
        TransitionRecommendationRequest request,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(_modelPath))
        {
            throw new InvalidOperationException("Trained model checkpoint was not found.");
        }

        if (!Directory.Exists(_featuresDir))
        {
            throw new InvalidOperationException("Feature directory was not found.");
        }

        var outputPath = Path.Combine(Path.GetTempPath(), $"mixerai-recommend-{Guid.NewGuid():N}.json");
        try
        {
            var processStartInfo = new ProcessStartInfo
            {
                FileName = _pythonExecutable,
                WorkingDirectory = _repoRoot,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            processStartInfo.ArgumentList.Add("ai/recommend_transitions.py");
            processStartInfo.ArgumentList.Add("--model-path");
            processStartInfo.ArgumentList.Add(_modelPath);
            processStartInfo.ArgumentList.Add("--features-dir");
            processStartInfo.ArgumentList.Add(_featuresDir);
            processStartInfo.ArgumentList.Add("--left-set-id");
            processStartInfo.ArgumentList.Add(request.LeftSetId);
            processStartInfo.ArgumentList.Add("--right-set-id");
            processStartInfo.ArgumentList.Add(request.RightSetId);
            processStartInfo.ArgumentList.Add("--top-k");
            processStartInfo.ArgumentList.Add(Math.Clamp(request.TopK, 1, 20).ToString());
            processStartInfo.ArgumentList.Add("--min-segment-index");
            processStartInfo.ArgumentList.Add(Math.Max(0, request.MinSegmentIndex).ToString());
            processStartInfo.ArgumentList.Add("--output-path");
            processStartInfo.ArgumentList.Add(outputPath);

            using var process = Process.Start(processStartInfo)
                ?? throw new InvalidOperationException("Failed to start Python inference process.");

            await process.WaitForExitAsync(cancellationToken);
            if (process.ExitCode != 0)
            {
                var error = await process.StandardError.ReadToEndAsync(cancellationToken);
                throw new InvalidOperationException($"Python inference failed: {error}");
            }

            if (!File.Exists(outputPath))
            {
                throw new InvalidOperationException("Python inference did not produce an output file.");
            }

            var payload = await File.ReadAllTextAsync(outputPath, cancellationToken);
            var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
            var results = JsonSerializer.Deserialize<List<TransitionRecommendation>>(payload, options);
            return results ?? [];
        }
        finally
        {
            if (File.Exists(outputPath))
            {
                File.Delete(outputPath);
            }
        }
    }
}
