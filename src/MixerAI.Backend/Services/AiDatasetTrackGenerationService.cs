using System.Diagnostics;
using MixerAI.Backend.Models;

namespace MixerAI.Backend.Services;

public sealed class AiDatasetTrackGenerationService
{
    private readonly string _repoRoot;
    private readonly string _pythonExecutable;
    private readonly string _rendersRoot;
    private readonly string[] _latentAutoencoderPathCandidates;
    private readonly string[] _latentGeneratorPathCandidates;
    private readonly string[] _phraseModelPathCandidates;

    public AiDatasetTrackGenerationService(IHostEnvironment environment)
    {
        _repoRoot = Path.GetFullPath(Path.Combine(environment.ContentRootPath, "..", ".."));
        _pythonExecutable = "python";
        _rendersRoot = Path.Combine(environment.ContentRootPath, "App_Data", "GeneratedTracks");
        _latentAutoencoderPathCandidates =
        [
            Path.Combine(_repoRoot, "data", "training", "audio_latent_autoencoder.pt")
        ];
        _latentGeneratorPathCandidates =
        [
            Path.Combine(_repoRoot, "data", "training", "latent_phrase_generator.pt")
        ];
        _phraseModelPathCandidates =
        [
            Path.Combine(_repoRoot, "data", "training", "phrase_token_generator.pt")
        ];
        Directory.CreateDirectory(_rendersRoot);
    }

    public async Task<MixRenderResult> GenerateAsync(GenerateDatasetTrackRequest request, CancellationToken cancellationToken)
    {
        var style = NormalizeStyle(request.Style);
        var durationSeconds = Math.Clamp(request.DurationSeconds, 96, 240);
        var seed = request.Seed ?? Random.Shared.Next(1, 1_000_000);

        var latentAutoencoderPath = ResolveOptionalPath(_latentAutoencoderPathCandidates);
        var latentGeneratorPath = ResolveOptionalPath(_latentGeneratorPathCandidates);
        var phraseModelPath = ResolveOptionalPath(_phraseModelPathCandidates);

        var useLatentGenerator = !string.IsNullOrWhiteSpace(latentAutoencoderPath) && !string.IsNullOrWhiteSpace(latentGeneratorPath);
        if (useLatentGenerator)
        {
            EnsureRequiredFile(latentAutoencoderPath!);
            EnsureRequiredFile(latentGeneratorPath!);
        }
        else
        {
            phraseModelPath ??= ResolvePhraseModelPath();
            EnsureRequiredFile(phraseModelPath);
        }

        var generationId = Guid.NewGuid().ToString("N");
        var workingDirectory = Path.Combine(_rendersRoot, generationId);
        Directory.CreateDirectory(workingDirectory);
        var outputPath = Path.Combine(workingDirectory, $"generated-{style}.mp3");

        var processStartInfo = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = _repoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        if (useLatentGenerator)
        {
            processStartInfo.ArgumentList.Add("ai/generation/generate_latent_track.py");
            processStartInfo.ArgumentList.Add("--autoencoder-model-path");
            processStartInfo.ArgumentList.Add(latentAutoencoderPath!);
            processStartInfo.ArgumentList.Add("--generator-model-path");
            processStartInfo.ArgumentList.Add(latentGeneratorPath!);
        }
        else
        {
            processStartInfo.ArgumentList.Add("ai/generation/generate_phrase_track.py");
            processStartInfo.ArgumentList.Add("--model-path");
            processStartInfo.ArgumentList.Add(phraseModelPath!);
        }
        processStartInfo.ArgumentList.Add("--style");
        processStartInfo.ArgumentList.Add(style);
        processStartInfo.ArgumentList.Add("--duration-seconds");
        processStartInfo.ArgumentList.Add(durationSeconds.ToString());
        processStartInfo.ArgumentList.Add("--seed");
        processStartInfo.ArgumentList.Add(seed.ToString());
        processStartInfo.ArgumentList.Add("--output-path");
        processStartInfo.ArgumentList.Add(outputPath);

        using var process = Process.Start(processStartInfo)
            ?? throw new InvalidOperationException("Failed to start phrase track generation process.");

        await process.WaitForExitAsync(cancellationToken);
        if (process.ExitCode != 0)
        {
            var error = await process.StandardError.ReadToEndAsync(cancellationToken);
            if (string.IsNullOrWhiteSpace(error))
            {
                error = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            }

            throw new InvalidOperationException($"Track generation failed: {SummarizeError(error)}");
        }

        if (!File.Exists(outputPath))
        {
            throw new InvalidOperationException("Track generation did not produce audio output.");
        }

        return new MixRenderResult
        {
            FileName = $"beatmix-{style}-{generationId}.mp3",
            Content = await File.ReadAllBytesAsync(outputPath, cancellationToken),
        };
    }

    private static string? ResolveOptionalPath(IEnumerable<string> candidates)
    {
        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private string ResolvePhraseModelPath()
    {
        foreach (var modelPath in _phraseModelPathCandidates)
        {
            if (File.Exists(modelPath))
            {
                return modelPath;
            }
        }

        throw new InvalidOperationException(
            "Phrase generator checkpoint not found. Train it first with "
            + "`python ai/generation/train_phrase_token_generator.py --train-split-path data/training/generation_splits/train.jsonl "
            + "--validation-split-path data/training/generation_splits/validation.jsonl --clips-root data/generated_clips`.");
    }

    private static void EnsureRequiredFile(string path)
    {
        if (!File.Exists(path))
        {
            throw new InvalidOperationException($"Required generator checkpoint not found: {path}");
        }
    }

    private static string NormalizeStyle(string? style)
    {
        var normalized = (style ?? string.Empty).Trim().ToLowerInvariant();
        return normalized switch
        {
            "liquid" => "liquid",
            "deep" => "deep",
            _ => throw new InvalidOperationException("Style must be either 'liquid' or 'deep'."),
        };
    }

    private static string SummarizeError(string error)
    {
        if (string.IsNullOrWhiteSpace(error))
        {
            return "Unknown generation error.";
        }

        var normalized = error.Replace("\r", " ").Replace("\n", " ").Trim();
        if (normalized.Length > 320)
        {
            normalized = normalized[..320] + "...";
        }

        return normalized;
    }
}
