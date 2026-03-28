using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Controllers;
using MixerAI.Web.Services;

namespace MixerAI.Backend.Tests.Web;

public class AccountControllerTests
{
    [Fact]
    public async Task Login_SignsInWithTokenClaimsAndDoesNotAppendReadableCookie()
    {
        var authService = new FakeAuthenticationService();
        await using var serviceProvider = TestHelpers.BuildAuthServiceProvider(authService);
        var backend = new FakeMixerBackendClient
        {
            LoginResult = new MixerBackendClient.LoginResponse(
                true,
                TestHelpers.CreateUnsignedJwt("user-123", "dj@example.com", "DJ Nova"))
        };

        var controller = new AccountController(backend);
        var httpContext = TestHelpers.CreateHttpContext();
        httpContext.RequestServices = serviceProvider;
        controller.ControllerContext = new ControllerContext { HttpContext = httpContext };

        var result = await controller.Login("dj@example.com", "secret", "/workspace");

        var redirect = Assert.IsType<LocalRedirectResult>(result);
        Assert.Equal("/workspace", redirect.Url);
        Assert.NotNull(authService.SignedInPrincipal);
        Assert.Equal("user-123", authService.SignedInPrincipal!.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value);
        Assert.Equal("dj@example.com", authService.SignedInPrincipal.FindFirst(System.Security.Claims.ClaimTypes.Email)?.Value);
        Assert.False(httpContext.Response.Headers.ContainsKey("Set-Cookie"));
    }
}
