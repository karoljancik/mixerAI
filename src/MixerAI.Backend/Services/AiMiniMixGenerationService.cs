using System.Diagnostics;
using MixerAI.Backend.Models;

namespace MixerAI.Backend.Services;

public sealed class AiMiniMixGenerationService
{
    private readonly string _repoRoot;
    private readonly string _pythonExecutable;
    private readonly string _rendersRoot;
    private readonly string _rawSetsPath;

    public AiMiniMixGenerationService(IHostEnvironment environment)
    {
        _repoRoot = Path.GetFullPath(Path.Combine(environment.ContentRootPath, "..", ".."));
        _pythonExecutable = "python";
        _rendersRoot = Path.Combine(environment.ContentRootPath, "App_Data", "MiniMixes");
        _rawSetsPath = Path.Combine(_repoRoot, "data", "raw_sets");
        Directory.CreateDirectory(_rendersRoot);
    }

    public async Task<MixRenderResult> GenerateMiniMixAsync(int? seed, CancellationToken cancellationToken)
    {
        var generationId = Guid.NewGuid().ToString("N");
        var outputPath = Path.Combine(_rendersRoot, $"minimix-{generationId}.mp3");

        var processStartInfo = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = _repoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        processStartInfo.ArgumentList.Add("ai/generate_mini_mix.py");
        processStartInfo.ArgumentList.Add("--input-dir");
        processStartInfo.ArgumentList.Add(_rawSetsPath);
        processStartInfo.ArgumentList.Add("--output-path");
        processStartInfo.ArgumentList.Add(outputPath);

        if (seed is int providedSeed)
        {
            processStartInfo.ArgumentList.Add("--seed");
            processStartInfo.ArgumentList.Add(providedSeed.ToString());
        }

        using var process = Process.Start(processStartInfo)
            ?? throw new InvalidOperationException("Failed to start mini mix generation process.");

        // Medior level: Registracia CancellationTokenu, aby sa Python proces zastavil, ak sa zrusi HTTP poziadavka 
        using var registration = cancellationToken.Register(() =>
        {
            if (!process.HasExited)
            {
                try { process.Kill(entireProcessTree: true); } catch { }
            }
        });

        try
        {
            await process.WaitForExitAsync(cancellationToken);
        }
        catch (TaskCanceledException)
        {
            throw new InvalidOperationException("Poziadavka bola zrusena klientom zatial co prebiehalo generovanie (Python proces bol ukonceny).");
        }

        if (process.ExitCode != 0)
        {
            var error = await process.StandardError.ReadToEndAsync(cancellationToken);
            if (string.IsNullOrWhiteSpace(error))
            {
                error = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            }
            throw new InvalidOperationException($"Mini mix failed: {error}");
        }

        if (!File.Exists(outputPath))
        {
            throw new InvalidOperationException("Mini mix did not produce output.");
        }

        return new MixRenderResult
        {
            FileName = $"1_30_minimix_{generationId}.mp3",
            Content = await File.ReadAllBytesAsync(outputPath, cancellationToken),
        };
    }
}
