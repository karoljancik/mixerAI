using MixerAI.Backend.Infrastructure;

namespace MixerAI.Backend.Workers;

public class QueuedHostedService : BackgroundService
{
    private readonly ILogger<QueuedHostedService> _logger;
    private readonly IBackgroundTaskQueue _taskQueue;
    private readonly IServiceProvider _serviceProvider;

    public QueuedHostedService(
        IBackgroundTaskQueue taskQueue,
        ILogger<QueuedHostedService> logger,
        IServiceProvider serviceProvider)
    {
        _taskQueue = taskQueue;
        _logger = logger;
        _serviceProvider = serviceProvider;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Queued Hosted Service is starting with parallel execution (max 3).");

        var maxConcurrency = 2; // Reduced from 3 to avoid memory pressure and segfaults
        var semaphore = new SemaphoreSlim(maxConcurrency);
        var tasks = new List<Task>();

        while (!stoppingToken.IsCancellationRequested)
        {
            var workItem = await _taskQueue.DequeueAsync(stoppingToken);

            await semaphore.WaitAsync(stoppingToken);

            var task = Task.Run(async () =>
            {
                try
                {
                    await workItem(_serviceProvider, stoppingToken);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error occurred executing work item.");
                }
                finally
                {
                    semaphore.Release();
                }
            }, stoppingToken);

            tasks.Add(task);
            
            // Periodically clean up completed tasks to prevent memory growth
            if (tasks.Count > 20)
            {
                tasks.RemoveAll(t => t.IsCompleted);
            }
        }

        _logger.LogInformation("Queued Hosted Service is stopping. Waiting for active tasks...");
        await Task.WhenAll(tasks);
    }
}
