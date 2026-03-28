using Microsoft.AspNetCore.Authentication.Cookies;
using MixerAI.Web.Configuration;
using MixerAI.Web.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();
builder.Logging.AddConsole();
builder.Logging.AddDebug();

builder.Services.AddControllersWithViews();
builder.Services.Configure<BackendApiOptions>(builder.Configuration.GetSection(BackendApiOptions.SectionName));
builder.Services.AddHttpContextAccessor();

builder.Services.AddHttpClient<MixerBackendClient>(client =>
{
    client.Timeout = TimeSpan.FromMinutes(15);
});


builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(options =>
    {
        options.LoginPath = "/Account/Login";
        options.AccessDeniedPath = "/Home/Error";
    });
builder.Services.AddAuthorization(options =>
{
    // Medior úroveň: Všetok obsah okrem povoleného explicitne bude pod Loginom
    options.FallbackPolicy = new Microsoft.AspNetCore.Authorization.AuthorizationPolicyBuilder()
        .RequireAuthenticatedUser()
        .Build();
});

var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
}

app.UseRouting();

// Pridana autentifikacia tiez na frontende
app.UseAuthentication();
app.UseAuthorization();


app.MapStaticAssets().AllowAnonymous();
app.MapControllerRoute(
        name: "default",
        pattern: "{controller=Home}/{action=Index}/{id?}")
    .WithStaticAssets();

app.Run();
