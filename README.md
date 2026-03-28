# MixerAI

MixerAI is a prototype DJ mixing app for drum and bass tracks. It lets you build a personal library, drag tracks onto two decks, preview them in a studio-style UI, and generate an AI-assisted transition render.

## What The App Does

- Upload tracks into a personal library
- Analyze uploaded tracks for BPM, Camelot key, duration, and waveform preview
- Load tracks onto Deck A / Deck B with drag and drop
- Preview both decks in a DJ studio interface
- Generate a mixed MP3 from two library tracks
- Use beat-sync, structure heuristics, and transition planning instead of a single plain crossfade

## Current Architecture

- [src/MixerAI.Web](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Web)
  ASP.NET Core MVC frontend with login, library, and DJ studio UI
- [src/MixerAI.Backend](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend)
  ASP.NET Core backend API for auth, library storage, track analysis, and mix rendering
- [ai](c:/Users/Administrator/Desktop/Osobne/mixerAI/ai)
  Python analysis and rendering scripts for BPM analysis, transition planning, and audio rendering
- [docker-compose.yml](c:/Users/Administrator/Desktop/Osobne/mixerAI/docker-compose.yml)
  Local multi-container setup for web, backend, and PostgreSQL

## Current User Flow

1. Register or log in
2. Upload tracks into the library
3. Wait for backend analysis to finish
4. Drag tracks from the library onto Deck A and Deck B
5. Preview the decks in the studio UI
6. Click `Generate Mix` to render an MP3 transition between the selected tracks

## Mix Engine Today

The current render path is hybrid:

- Track analysis extracts tempo and lightweight structure information
- The planner tries to find a musically plausible transition point
- Track B is tempo-aligned to Track A
- The renderer builds an overlap zone where both tracks can play together
- Different transition styles can be chosen, such as `double_drop`, `bass_swap`, `echo_out`, or a general blend

Important notes:

- The generated mix is currently heuristic-first
- If the trained `transition_scorer.pt` checkpoint does not match the current feature set, the backend falls back to deterministic heuristics instead of failing
- This project is still in active tuning; transition timing and EQ behavior are not considered final

## Studio UI Notes

- Track loading in the studio is based on drag and drop from the library
- The `CF` slider is only a live preview crossfader for deck playback in the browser
- The `CF` slider does not change the server-rendered mix output

## Running With Docker

Recommended local setup:

```powershell
docker compose up --build
```

Services:

- Web: `http://localhost:5000`
- Backend: `http://localhost:8080`
- PostgreSQL: `localhost:5432`

To run in the background:

```powershell
docker compose up --build -d
```

To stop everything:

```powershell
docker compose down
```

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

## Data And Storage

- Uploaded library tracks are stored under backend `App_Data/UserTracks`
- Rendered mixes are stored under backend `App_Data/RenderedMixes`
- Docker volumes keep uploaded tracks and renders persistent across rebuilds
- Training and model assets live under [data](c:/Users/Administrator/Desktop/Osobne/mixerAI/data)

## AI / Training Direction

The longer-term direction is:

1. Keep the upload, library, and render pipeline stable
2. Improve track structure analysis and DJ-style transition logic
3. Rebuild the transition feature set so the learned model matches the live render pipeline
4. Only then rely more heavily on trained transition scoring

The project already includes:

- weakly supervised transition-pair generation
- transition scorer training scripts
- generation dataset preparation
- phrase and latent audio generation experiments

For details, see [ai/README.md](c:/Users/Administrator/Desktop/Osobne/mixerAI/ai/README.md).

## Current Limitations

- Transition quality is still being tuned
- Some heuristic choices are good on some pairs and weak on others
- The trained transition checkpoint may be outdated relative to the current feature schema
- The app is optimized around drum and bass assumptions, especially for BPM normalization and phrase alignment

## Useful Paths

- [src/MixerAI.Web/Views/Home/Index.cshtml](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Web/Views/Home/Index.cshtml)
  DJ studio view
- [src/MixerAI.Backend/Program.cs](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend/Program.cs)
  Main API wiring
- [src/MixerAI.Backend/Controllers/LibraryController.cs](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend/Controllers/LibraryController.cs)
  Track upload, delete, and audio file serving
- [src/MixerAI.Backend/Services/AiMixRenderService.cs](c:/Users/Administrator/Desktop/Osobne/mixerAI/src/MixerAI.Backend/Services/AiMixRenderService.cs)
  Backend bridge to Python mix rendering
- [ai/render_mix.py](c:/Users/Administrator/Desktop/Osobne/mixerAI/ai/render_mix.py)
  Core transition planning and render logic
