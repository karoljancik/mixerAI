using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging.Abstractions;
using MixerAI.Backend.Infrastructure;

namespace MixerAI.Backend.Tests.Backend;

public class GlobalExceptionHandlerTests
{
    [Fact]
    public async Task TryHandleAsync_ReturnsBadRequestPayloadForInvalidOperation()
    {
        var handler = new GlobalExceptionHandler(new NullLogger<GlobalExceptionHandler>());
        var context = new DefaultHttpContext();
        context.Response.Body = new MemoryStream();

        var handled = await handler.TryHandleAsync(context, new InvalidOperationException("broken mix"), CancellationToken.None);

        Assert.True(handled);
        Assert.Equal(StatusCodes.Status400BadRequest, context.Response.StatusCode);

        context.Response.Body.Position = 0;
        var payload = await JsonDocument.ParseAsync(context.Response.Body);
        Assert.Equal("broken mix", payload.RootElement.GetProperty("error").GetString());
        Assert.Equal("InvalidOperationException", payload.RootElement.GetProperty("type").GetString());
    }
}
