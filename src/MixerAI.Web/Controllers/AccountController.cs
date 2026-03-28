using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;

namespace MixerAI.Web.Controllers;

[Microsoft.AspNetCore.Authorization.AllowAnonymous]
public class AccountController : Controller
{
    private readonly Services.MixerBackendClient _backendClient;

    public AccountController(Services.MixerBackendClient backendClient)
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
    public async Task<IActionResult> Login(string email, string password, string returnUrl = "/")
    {
        // V Medior aplikácii voláme backendove Identity Endpointy
        var response = await _backendClient.LoginAsync(email, password);
        
        if (response.IsSuccess)
        {
            var claims = new List<Claim>
            {
                new Claim(ClaimTypes.NameIdentifier, email),
                new Claim(ClaimTypes.Name, email),
                new Claim("AccessToken", response.Token) // Uložíme si Bearer token pre ďalšie API volania
            };

            var identity = new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme);
            await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme, new ClaimsPrincipal(identity));

            // Set a cookie for the AccessToken so JS can read it for SignalR
            Response.Cookies.Append("AccessToken", response.Token, new CookieOptions { 
                HttpOnly = false, 
                Secure = true, 
                SameSite = SameSiteMode.Strict 
            });

            return LocalRedirect(returnUrl);
        }

        ModelState.AddModelError(string.Empty, "Zlé prihlasovacie údaje.");
        return View();
    }

    [HttpGet]
    public IActionResult Register()
    {
        return View();
    }

    [HttpPost]
    public async Task<IActionResult> Register(string email, string password)
    {
        var success = await _backendClient.RegisterAsync(email, password);
        if (success)
        {
            return RedirectToAction(nameof(Login));
        }

        ModelState.AddModelError(string.Empty, "Registrácia zlyhala. Účet už asi existuje alebo je slabé heslo.");
        return View();
    }

    [HttpPost]
    public async Task<IActionResult> Logout()
    {
        await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
        return RedirectToAction("Index", "Home");
    }
}
