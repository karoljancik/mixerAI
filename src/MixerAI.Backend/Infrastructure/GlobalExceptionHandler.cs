using Microsoft.AspNetCore.Diagnostics;

namespace MixerAI.Backend.Infrastructure;

public sealed class GlobalExceptionHandler : IExceptionHandler
{
    private readonly ILogger<GlobalExceptionHandler> _logger;

    public GlobalExceptionHandler(ILogger<GlobalExceptionHandler> logger)
    {
        _logger = logger;
    }

    public async ValueTask<bool> TryHandleAsync(
        HttpContext httpContext,
        Exception exception,
        CancellationToken cancellationToken)
    {
        _logger.LogError(exception, "Nastala necakana chyba pocas spracovania poziadavky.");

        var statusCode = exception switch
        {
            BadHttpRequestException => StatusCodes.Status400BadRequest,
            ArgumentException => StatusCodes.Status400BadRequest,
            InvalidOperationException => StatusCodes.Status400BadRequest,
            TaskCanceledException => StatusCodes.Status499ClientClosedRequest,
            _ => StatusCodes.Status500InternalServerError
        };

        httpContext.Response.StatusCode = statusCode;
        
        await httpContext.Response.WriteAsJsonAsync(new
        {
            error = exception.Message,
            type = exception.GetType().Name
        }, cancellationToken);

        return true;
    }
}
