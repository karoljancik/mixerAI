# MixerAI

MixerAI is an AI-powered DJ and producer workspace for drum and bass. It combines track library management, transition coaching, set recommendation, and generative sketching in one full-stack .NET plus Python app.

## Product Story

The app is now framed as a copilot for young DJs and producers:

- upload tracks into a personal library
- analyze them for BPM, Camelot key, waveform preview, and processing health
- load tracks onto Deck A and Deck B in the studio workspace
- get AI transition coaching based on tempo and key fit
- render an AI-assisted transition reference mix from your own library
- ask the recommendation engine for promising transitions across the offline set corpus
- generate short producer sketches or mini-mix inspiration from the trained generation pipeline

This keeps the human in the loop. MixerAI helps users understand how tracks can fit together, not just click a single magic button.

## Architecture

- [src/MixerAI.Web](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Web)
  ASP.NET Core MVC frontend with cookie auth, library management, and the unified AI workspace
- [src/MixerAI.Backend](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend)
  ASP.NET Core backend API for auth, track storage, retryable analysis, recommendations, and rendering
- [src/MixerAI.Backend/Data/Migrations](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend/Data/Migrations)
  EF Core migrations used on startup through `Database.Migrate()`
- [ai](c:/Users/Administrator/Desktop/Osobne/mixerAI/ai)
  Python analysis, recommendation, rendering, and generation scripts
- [tests/MixerAI.Backend.Tests](c:/Users/Administrator/Desktop/Osobne/mixerAI/tests/MixerAI.Backend.Tests)
  Automated tests covering key controller flows and backend error handling

## Current Flow

1. Register or log in.
2. Upload tracks in the library.
3. Let the backend analyze each track in the background.
4. Retry failed analyses directly from the UI if needed.
5. Drag ready tracks onto the decks in the workspace.
6. Generate an AI-assisted transition reference mix.
7. Explore corpus-backed transition recommendations.
8. Generate producer sketches or a mini-mix inspiration file.

## Reliability Improvements

Recent app-level improvements:

- backend startup now applies EF Core migrations instead of relying on `EnsureCreated()`
- the auth flow keeps the bearer token inside the server-side auth ticket instead of a JS-readable cookie
- track analysis failures now store an error reason, increment attempt counts, and expose retry actions
- the home page uses a single workspace view model instead of mismatched page models
- automated tests cover key web and backend flows

## Running With Docker

```powershell
docker compose up --build
```

Services:

- Web: `http://localhost:5000`
- Backend: `http://localhost:8080`
- PostgreSQL: `localhost:5432`

## Running Without Docker

Backend:

```powershell
$env:DOTNET_CLI_HOME='c:\Users\Administrator\Desktop\Osobne\mixerAI'
dotnet run --project src/MixerAI.Backend
```

Frontend:

```powershell
$env:DOTNET_CLI_HOME='c:\Users\Administrator\Desktop\Osobne\mixerAI'
dotnet run --project src/MixerAI.Web
```

Python scripts expect:

- `python`
- `ffmpeg`
- `ffprobe`

## Database And Storage

- Uploaded tracks are stored under backend `App_Data/UserTracks`
- Rendered mixes are stored under backend `App_Data/RenderedMixes`
- Generated sketches are stored under backend `App_Data/GeneratedTracks`
- Docker volumes keep user uploads and renders persistent across rebuilds

## Tests

Run the automated checks with:

```powershell
$env:DOTNET_CLI_HOME='c:\Users\Administrator\Desktop\Osobne\mixerAI'
dotnet build src/MixerAI.Backend/MixerAI.Backend.csproj --no-restore
dotnet build src/MixerAI.Web/MixerAI.Web.csproj --no-restore
dotnet test tests/MixerAI.Backend.Tests/MixerAI.Backend.Tests.csproj --no-build
```

## Useful Paths

- [src/MixerAI.Web/Views/Home/Index.cshtml](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Web/Views/Home/Index.cshtml)
  unified AI DJ producer workspace
- [src/MixerAI.Backend/Controllers/LibraryController.cs](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend/Controllers/LibraryController.cs)
  upload, delete, retry analysis, and audio file serving
- [src/MixerAI.Backend/Services/TrackAnalysisService.cs](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend/Services/TrackAnalysisService.cs)
  observable track analysis workflow with attempts and stored error reasons
- [src/MixerAI.Backend/Services/AiMixRenderService.cs](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend/Services/AiMixRenderService.cs)
  backend bridge to Python mix rendering
- [ai/README.md](c:/Users/Administrator/Desktop/Osobne/mixerAI/ai/README.md)
  training and generation direction
