using System.Security.Claims;
using System.Text.Json;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using MixerAI.Web.Contracts;
using MixerAI.Web.Services;

namespace MixerAI.Web.Controllers;

[ApiController]
[Route("api/bff/auth")]
public sealed class AuthController : ControllerBase
{
    private readonly IMixerBackendClient _backendClient;

    public AuthController(IMixerBackendClient backendClient)
    {
        _backendClient = backendClient;
    }

    [HttpGet("session")]
    [AllowAnonymous]
    public ActionResult<SessionResponse> GetSession()
    {
        return Ok(BuildSessionResponse(User));
    }

    [HttpPost("login")]
    [AllowAnonymous]
    public async Task<ActionResult<SessionResponse>> Login([FromBody] LoginRequest request)
    {
        var response = await _backendClient.LoginAsync(request.Email, request.Password);
        if (!response.IsSuccess)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = "Sign-in failed. Double-check your email and password."
            });
        }

        await SignInAsync(request.Email, response.Token);
        return Ok(BuildSessionResponse(HttpContext.User));
    }

    [HttpPost("register")]
    [AllowAnonymous]
    public async Task<ActionResult<SessionResponse>> Register([FromBody] RegisterRequest request)
    {
        var registered = await _backendClient.RegisterAsync(request.Email, request.Password);
        if (!registered)
        {
            return BadRequest(new ApiErrorResponse
            {
                Error = "Registration failed. The account may already exist or the password policy was not met."
            });
        }

        var login = await _backendClient.LoginAsync(request.Email, request.Password);
        if (!login.IsSuccess)
        {
            return Ok(new SessionResponse
            {
                IsAuthenticated = false
            });
        }

        await SignInAsync(request.Email, login.Token);
        return Ok(BuildSessionResponse(HttpContext.User));
    }

    [HttpPost("logout")]
    [Authorize]
    public async Task<IActionResult> Logout()
    {
        await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
        return NoContent();
    }

    private async Task SignInAsync(string fallbackEmail, string accessToken)
    {
        var identity = new ClaimsIdentity(BuildClaims(fallbackEmail, accessToken), CookieAuthenticationDefaults.AuthenticationScheme);
        var principal = new ClaimsPrincipal(identity);
        await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme, principal);
        HttpContext.User = principal;
    }

    private static SessionResponse BuildSessionResponse(ClaimsPrincipal principal)
    {
        var isAuthenticated = principal.Identity?.IsAuthenticated == true;

        return new SessionResponse
        {
            IsAuthenticated = isAuthenticated,
            DisplayName = isAuthenticated ? principal.Identity?.Name : null,
            Email = isAuthenticated ? principal.FindFirst(ClaimTypes.Email)?.Value : null
        };
    }

    private static IReadOnlyList<Claim> BuildClaims(string fallbackEmail, string accessToken)
    {
        var payload = ReadJwtPayload(accessToken);
        var userId = ReadClaim(payload, "sub")
            ?? ReadClaim(payload, ClaimTypes.NameIdentifier)
            ?? fallbackEmail;
        var email = ReadClaim(payload, "email")
            ?? ReadClaim(payload, ClaimTypes.Email)
            ?? fallbackEmail;
        var displayName = ReadClaim(payload, "unique_name")
            ?? ReadClaim(payload, ClaimTypes.Name)
            ?? email;

        return
        [
            new Claim(ClaimTypes.NameIdentifier, userId),
            new Claim(ClaimTypes.Name, displayName),
            new Claim(ClaimTypes.Email, email),
            new Claim("AccessToken", accessToken)
        ];
    }

    private static JsonElement? ReadJwtPayload(string token)
    {
        var parts = token.Split('.');
        if (parts.Length < 2)
        {
            return null;
        }

        try
        {
            var padded = parts[1]
                .Replace('-', '+')
                .Replace('_', '/');
            padded = padded.PadRight(padded.Length + ((4 - padded.Length % 4) % 4), '=');

            var jsonBytes = Convert.FromBase64String(padded);
            return JsonDocument.Parse(jsonBytes).RootElement.Clone();
        }
        catch
        {
            return null;
        }
    }

    private static string? ReadClaim(JsonElement? payload, string claimType)
    {
        if (payload is not JsonElement element)
        {
            return null;
        }

        return element.TryGetProperty(claimType, out var value)
            ? value.GetString()
            : null;
    }
}
