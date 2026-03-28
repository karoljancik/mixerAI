namespace MixerAI.Backend.Infrastructure;

public static class TrackStoragePathResolver
{
    public static string ResolvePhysicalPath(string storageRoot, string storedPath)
    {
        var fileName = ExtractFileName(storedPath);
        return Path.Combine(storageRoot, fileName);
    }

    public static string ExtractFileName(string storedPath)
    {
        if (string.IsNullOrWhiteSpace(storedPath))
        {
            throw new InvalidOperationException("Track file path is empty.");
        }

        // Normalize both Windows and Unix separators before extracting the file name.
        var normalizedPath = storedPath.Replace('\\', '/');
        var fileName = Path.GetFileName(normalizedPath);

        if (string.IsNullOrWhiteSpace(fileName))
        {
            throw new InvalidOperationException("Track file path does not contain a valid file name.");
        }

        return fileName;
    }
}
