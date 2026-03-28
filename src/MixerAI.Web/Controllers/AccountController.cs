using System.Security.Claims;
using System.Text.Json;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;

namespace MixerAI.Web.Controllers;

[Microsoft.AspNetCore.Authorization.AllowAnonymous]
public class AccountController : Controller
{
    private readonly Services.IMixerBackendClient _backendClient;

    public AccountController(Services.IMixerBackendClient backendClient)
    {
        _backendClient = backendClient;
    }

    [HttpGet]
    public IActionResult Login(string returnUrl = "/")
    {
        ViewData["ReturnUrl"] = returnUrl;
        return View();
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Login(string email, string password, string returnUrl = "/")
    {
        var response = await _backendClient.LoginAsync(email, password);

        if (response.IsSuccess)
        {
            var identity = new ClaimsIdentity(BuildClaims(email, response.Token), CookieAuthenticationDefaults.AuthenticationScheme);
            await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme, new ClaimsPrincipal(identity));
            return LocalRedirect(returnUrl);
        }

        ModelState.AddModelError(string.Empty, "Zle prihlasovacie udaje.");
        return View();
    }

    [HttpGet]
    public IActionResult Register()
    {
        return View();
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Register(string email, string password)
    {
        var success = await _backendClient.RegisterAsync(email, password);
        if (success)
        {
            return RedirectToAction(nameof(Login));
        }

        ModelState.AddModelError(string.Empty, "Registracia zlyhala. Ucet uz asi existuje alebo je slabe heslo.");
        return View();
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Logout()
    {
        await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
        return RedirectToAction("Index", "Home");
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
