import { startTransition, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { api } from "./api";
import { WaveformCanvas } from "./components/WaveformCanvas";
import type {
  MixAnalysisResult,
  SessionResponse,
  Track,
  TransitionRecommendation,
  TransitionRecommendationRequest,
  WorkspaceSnapshot,
} from "./types";

type AuthMode = "login" | "register";
type Language = "sk" | "en";

type AuthFormState = {
  email: string;
  password: string;
};

const techPills = ["ASP.NET Core BFF", "React + TypeScript", "Python audio AI", "Portfolio demo"];

const copy = {
  sk: {
    language: "Jazyk",
    loadingTitle: "Načítavam DJ workspace",
    loadingBody: "Overujem session a pripravujem štúdio.",
    landingEyebrow: "AI DJ learning workspace",
    landingTitle: "Trénuj základy mixovania v prostredí inšpirovanom rekordbox workflow.",
    landingBody:
      "Nahraj tracky, vyber Deck A a Deck B, sleduj BPM a key fit, nechaj si poradiť kedy spustiť Track B a vygeneruj si automatický mix z dvoch trackov.",
    landingCards: [
      ["Nahraj knižnicu", "Backend dopočíta BPM, key a waveform dáta."],
      ["Nacvič prechod", "Porovnaj decky a skús si vlastný crossfade."],
      ["Porovnaj sa s AI", "Získaj cue timing a referenčný auto-mix."],
    ],
    landingFeatures: [
      ["Beginner deck view", "Dva decky, waveformy a lokálny crossfader bez zbytočného balastu."],
      ["AI cue guidance", "Model navrhne, kde je dobré pustiť Track B do Tracku A."],
      ["Automatic mix", "Stiahni si referenčný mix z dvoch vybraných trackov."],
    ],
    authTitle: "Vstup do štúdia",
    authBody: "Portfólio ostáva technické, ale produktový obsah je teraz zameraný na učenie DJ základov.",
    signIn: "Prihlásiť",
    createAccount: "Vytvoriť účet",
    openWorkspace: "Otvoriť workspace",
    createDemoAccount: "Vytvoriť demo účet",
    email: "Email",
    password: "Heslo",
    passwordPlaceholder: "Aspoň 6 znakov",
    topbarEyebrow: "AI-assisted DJ portfolio app",
    studioTitle: "MixerAI Studio",
    heroTitle: (name: string) => `${name}, toto je tvoje vedené mixovacie štúdio.`,
    heroBody:
      "Frontend je uprataný na to podstatné pre začiatočníka: library, decky, AI navigácia načasovania a automatické generovanie mixu.",
    heroCards: [
      ["1. Vyber decky", "Najprv si priprav dvojicu trackov, ktorú chceš skúšať mixovať."],
      ["2. Sleduj AI radu", "Pozri si BPM, key a odporúčaný moment na vstup Tracku B."],
      ["3. Stiahni referenciu", "Porovnaj vlastný prechod s automaticky vygenerovaným mixom."],
    ],
    stackTitle: "Portfolio stack",
    stackBody: "Same-origin React SPA nad ASP.NET Core BFF vrstvou a Python audio pipeline.",
    readyTracks: "Pripravené tracky",
    needsAttention: "Na kontrolu",
    referenceSets: "Referenčné sety",
    refresh: "Obnoviť dáta",
    refreshing: "Obnovujem...",
    signOut: "Odhlásiť",
    signedInAs: "Prihlásený ako",
    mixCoach: "Mix coach",
    mixCoachTitle: "Vyber dva tracky a nacvič si prechod",
    mixCoachBody: "Tu sa sústreďuje hlavný rekordbox-like flow: výber deckov, timing rady a auto-mix.",
    mixCoachEmpty: "Nahraj a analyzuj aspoň dva tracky, aby sa odomkol plný guided workflow.",
    deckA: "Deck A",
    deckB: "Deck B",
    chooseTrack: "Vyber pripravený track",
    noTrack: "Žiadny track nie je načítaný",
    noArtist: "Interpret zatiaľ nie je dostupný",
    crossfaderTitle: "Crossfader preview",
    crossfaderBody: "Lokálne si nastav pomer deckov ešte pred generovaním mixu.",
    adviceTitle: "AI timing guidance",
    renderHint: "Ber to ako referenciu k tréningu, nie náhradu za vlastné rozhodovanie.",
    renderMix: "Vygenerovať automatický mix",
    renderingMix: "Renderujem automatický mix...",
    planner: "AI cue planner",
    plannerTitle: "Použi referenčné sety na odhad handover momentu",
    plannerBody: "Model zoradí kandidátov z korpusu a pomôže ti pochopiť, kde blend pravdepodobne zafunguje.",
    leftSet: "Referenčný set A",
    rightSet: "Referenčný set B",
    chooseSet: "Vyber set",
    topCandidates: "Počet kandidátov",
    findCues: "Nájsť cue body",
    findingCues: "Počítam odporúčania...",
    fit: "Zhoda",
    noRecommendations: "Spusť AI cue planner a zobraz si odporúčané prechodové okná.",
    basics: "Mixing basics",
    basicsTitle: "Na čo sa sústrediť",
    basicsBody: "Krátke praktické tipy podľa vybraných trackov.",
    analyzer: "Transition analyzer",
    analyzerTitle: "Skontroluj dva súbory ešte pred pridaním do knižnice",
    analyzerBody: "Získaš BPM, beat markery a odporúčaný overlay bez nutnosti najprv všetko uploadovať.",
    analyze: "Analyzovať prechod",
    analyzing: "Analyzujem...",
    analyzerEmpty: "Nahraj dva tracky a zobrazí sa BPM detekcia, waveform preview aj odporúčaný bod prekrytia.",
    overlayStart: "Začiatok overlay-u",
    modelConfidence: "Istota modelu",
    trackABpm: "BPM Tracku A",
    trackBBpm: "BPM Tracku B",
    previewLength: (seconds: string) => `Dĺžka preview ${seconds}`,
    suggestedSource: (seconds: string) => `Odporúčaný vstup Tracku B ${seconds}`,
    library: "Library",
    libraryTitle: "Správa trackov pre demo flow",
    libraryBody: "Len dôležité operácie: upload, monitoring analýzy a rýchle poslanie tracku na deck.",
    uploadAudio: "Nahrať audio",
    table: ["Stav", "Názov", "BPM", "Key", "Dĺžka", "Pokusy", "Pridané", "Akcie"],
    emptyTable: "Nahraj prvý track a spusti celý guided workflow.",
    retry: "Skúsiť znova",
    delete: "Vymazať",
    ready: "Pripravené",
    analyzingStatus: "Analyzuje sa",
    attention: "Vyžaduje pozornosť",
    queued: "V rade",
    working: "Spracovávam...",
  },
  en: {
    language: "Language",
    loadingTitle: "Loading DJ workspace",
    loadingBody: "Checking your session and preparing the studio.",
    landingEyebrow: "AI DJ learning workspace",
    landingTitle: "Learn the basics of mixing in a rekordbox-inspired workflow.",
    landingBody:
      "Upload tracks, choose Deck A and Deck B, compare BPM and key fit, get help with when to launch Track B, and render an automatic mix from two tracks.",
    landingCards: [
      ["Build the library", "The backend extracts BPM, key and waveform data."],
      ["Practice transitions", "Compare the decks and test your own crossfade."],
      ["Compare with AI", "Get cue timing and a reference auto-mix."],
    ],
    landingFeatures: [
      ["Beginner deck view", "Two decks, waveforms and a local crossfader without extra clutter."],
      ["AI cue guidance", "The model suggests where Track B should enter Track A."],
      ["Automatic mix", "Download a reference mix from the two selected tracks."],
    ],
    authTitle: "Enter the studio",
    authBody: "The portfolio remains technical, but the product surface is now centered on learning DJ fundamentals.",
    signIn: "Sign in",
    createAccount: "Create account",
    openWorkspace: "Open workspace",
    createDemoAccount: "Create demo account",
    email: "Email",
    password: "Password",
    passwordPlaceholder: "At least 6 characters",
    topbarEyebrow: "AI-assisted DJ portfolio app",
    studioTitle: "MixerAI Studio",
    heroTitle: (name: string) => `${name}, here is your guided mixing studio.`,
    heroBody:
      "The frontend now focuses on what matters for a beginner: library prep, decks, AI timing guidance and automatic mix generation.",
    heroCards: [
      ["1. Choose the decks", "Prepare the pair of tracks you want to practice with."],
      ["2. Follow the AI guidance", "Review BPM, key and the suggested entry point for Track B."],
      ["3. Download the reference", "Compare your transition with the generated mix."],
    ],
    stackTitle: "Portfolio stack",
    stackBody: "A same-origin React SPA on top of an ASP.NET Core BFF and Python audio pipeline.",
    readyTracks: "Ready tracks",
    needsAttention: "Needs attention",
    referenceSets: "Reference sets",
    refresh: "Refresh data",
    refreshing: "Refreshing...",
    signOut: "Sign out",
    signedInAs: "Signed in as",
    mixCoach: "Mix coach",
    mixCoachTitle: "Choose two tracks and practice the transition",
    mixCoachBody: "This is the main rekordbox-like flow: deck selection, timing guidance and auto-mix.",
    mixCoachEmpty: "Upload and analyze at least two tracks to unlock the full guided workflow.",
    deckA: "Deck A",
    deckB: "Deck B",
    chooseTrack: "Choose a ready track",
    noTrack: "No track loaded",
    noArtist: "Artist metadata pending",
    crossfaderTitle: "Crossfader preview",
    crossfaderBody: "Balance the deck levels locally before generating the mix.",
    adviceTitle: "AI timing guidance",
    renderHint: "Treat it as a practice reference, not a replacement for your own ears.",
    renderMix: "Generate automatic mix",
    renderingMix: "Rendering automatic mix...",
    planner: "AI cue planner",
    plannerTitle: "Use reference sets to estimate the handover moment",
    plannerBody: "The model ranks candidates from the corpus and helps explain where a blend is likely to work.",
    leftSet: "Reference set A",
    rightSet: "Reference set B",
    chooseSet: "Choose a set",
    topCandidates: "Top candidates",
    findCues: "Find cue points",
    findingCues: "Ranking transitions...",
    fit: "Fit",
    noRecommendations: "Run the AI cue planner to surface likely transition windows.",
    basics: "Mixing basics",
    basicsTitle: "What to focus on",
    basicsBody: "A few practical tips based on the selected tracks.",
    analyzer: "Transition analyzer",
    analyzerTitle: "Inspect two files before adding them to the library",
    analyzerBody: "You get BPM, beat markers and a suggested overlay without uploading everything first.",
    analyze: "Analyze transition",
    analyzing: "Analyzing...",
    analyzerEmpty: "Upload two tracks to see BPM detection, waveform preview and the suggested overlap point.",
    overlayStart: "Overlay start",
    modelConfidence: "Model confidence",
    trackABpm: "Track A BPM",
    trackBBpm: "Track B BPM",
    previewLength: (seconds: string) => `Preview length ${seconds}`,
    suggestedSource: (seconds: string) => `Suggested Track B source ${seconds}`,
    library: "Library",
    libraryTitle: "Manage the tracks behind the demo flow",
    libraryBody: "Only the important operations remain: upload, analysis monitoring and quick deck assignment.",
    uploadAudio: "Upload audio",
    table: ["Status", "Title", "BPM", "Key", "Length", "Attempts", "Added", "Actions"],
    emptyTable: "Upload your first track to start the guided workflow.",
    retry: "Retry",
    delete: "Delete",
    ready: "Ready",
    analyzingStatus: "Analyzing",
    attention: "Needs attention",
    queued: "Queued",
    working: "Working...",
  },
} as const;

type AppCopy = (typeof copy)[Language];

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "--";
  }

  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

function formatDate(value: string | null, language: Language): string {
  if (!value) {
    return "--";
  }

  return new Intl.DateTimeFormat(language === "sk" ? "sk-SK" : "en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function parseWaveform(track: Track | null): number[] {
  if (!track?.waveformDataJson) {
    return [];
  }

  try {
    const parsed = JSON.parse(track.waveformDataJson) as number[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function buildAdvice(trackA: Track | null, trackB: Track | null, language: Language): string[] {
  if (!trackA || !trackB) {
    return [
      language === "sk"
        ? "Načítaj pripravený track do oboch deckov a porovnaj tempo, key a AI timing guidance."
        : "Load a ready track into both decks to compare tempo, key and AI timing guidance.",
    ];
  }

  const lines: string[] = [];

  if (trackA.bpm && trackB.bpm) {
    const delta = Math.abs(trackA.bpm - trackB.bpm);
    if (delta <= 3) {
      lines.push(
        language === "sk"
          ? `Tempo si sadá veľmi dobre: ${trackA.bpm.toFixed(1)} vs ${trackB.bpm.toFixed(1)} BPM.`
          : `Tempo fit is strong at ${trackA.bpm.toFixed(1)} vs ${trackB.bpm.toFixed(1)} BPM.`,
      );
    } else if (delta <= 8) {
      lines.push(
        language === "sk"
          ? `Rozdiel tempa je ${delta.toFixed(1)} BPM. Ľahký sync by mal stále fungovať čisto.`
          : `Tempo gap is ${delta.toFixed(1)} BPM. Light sync should still sound clean.`,
      );
    } else {
      lines.push(
        language === "sk"
          ? `Rozdiel tempa je ${delta.toFixed(1)} BPM. Track B bude potrebovať výraznejšiu korekciu.`
          : `Tempo gap is ${delta.toFixed(1)} BPM. Track B will need stronger correction.`,
      );
    }
  }

  if (trackA.camelotKey && trackB.camelotKey) {
    lines.push(
      trackA.camelotKey === trackB.camelotKey
        ? language === "sk"
          ? `Harmonický blend vyzerá čisto v key ${trackA.camelotKey}.`
          : `Harmonic blend looks clean in ${trackA.camelotKey}.`
        : language === "sk"
          ? `Skontroluj, ako pôsobí pohyb z key ${trackA.camelotKey} do ${trackB.camelotKey}.`
          : `Check how the move from ${trackA.camelotKey} to ${trackB.camelotKey} feels.`,
    );
  }

  lines.push(
    language === "sk"
      ? "Skús púšťať Track B na nový takt alebo novú frázu, aby prechod pôsobil prirodzene."
      : "Try launching Track B on a fresh bar or phrase so the transition feels intentional.",
  );
  lines.push(
    language === "sk"
      ? "Vyrenderuj automatický mix a porovnaj ho s vlastným manuálnym prechodom."
      : "Render the automatic mix and compare it with your own manual transition.",
  );

  return lines;
}

function buildTips(trackA: Track | null, trackB: Track | null, language: Language): string[] {
  if (!trackA || !trackB) {
    return language === "sk"
      ? [
          "Začni pármi trackov s podobným BPM. Beatmatching bude výrazne jednoduchší.",
          "Track B púšťaj pri phrase change, nie uprostred vokálu alebo dropu.",
          "AI render používaj ako kouča: vypočuj si timing, napodobni ho a dolaď podľa sluchu.",
        ]
      : [
          "Start with tracks that are close in BPM. Beatmatching will feel much more forgiving.",
          "Bring Track B in on a phrase change, not in the middle of a vocal or drop.",
          "Use the AI render as a coach: listen to the timing, copy it, then refine it by ear.",
        ];
  }

  const tips: string[] = [];

  if (trackA.bpm && trackB.bpm) {
    const delta = Math.abs(trackA.bpm - trackB.bpm);
    tips.push(
      delta <= 5
        ? language === "sk"
          ? `BPM rozdiel je len ${delta.toFixed(1)}. Toto je dobrá dvojica na prvý tréning beatmatchu.`
          : `The BPM gap is only ${delta.toFixed(1)}. This is a good beginner pairing for beatmatching.`
        : language === "sk"
          ? `BPM rozdiel je ${delta.toFixed(1)}. Tento pár si nechaj skôr na pokročilejší tréning.`
          : `The BPM gap is ${delta.toFixed(1)}. Save this pair for slightly more advanced practice.`,
    );
  }

  if (trackA.camelotKey && trackB.camelotKey) {
    tips.push(
      trackA.camelotKey === trackB.camelotKey
        ? language === "sk"
          ? `Oba tracky sú v key ${trackA.camelotKey}, takže sa môžeš sústrediť hlavne na phrasing a EQ.`
          : `Both tracks sit in ${trackA.camelotKey}, so you can focus on phrasing and EQ.`
        : language === "sk"
          ? `Key sa mení z ${trackA.camelotKey} do ${trackB.camelotKey}. Počúvaj, či sa nebijú pady alebo vokály.`
          : `The keys move from ${trackA.camelotKey} to ${trackB.camelotKey}. Listen for clashing pads or vocals.`,
    );
  }

  tips.push(
    language === "sk"
      ? "Počítaj 16 alebo 32 dôb na konci Tracku A a spusti Track B na ďalší downbeat."
      : "Count 16 or 32 beats near the end of Track A and trigger Track B on the next downbeat.",
  );

  return tips;
}

function triggerDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

function statusLabel(status: string, t: AppCopy): string {
  switch (status.toLowerCase()) {
    case "ready":
      return t.ready;
    case "analyzing":
      return t.analyzingStatus;
    case "error":
      return t.attention;
    default:
      return t.queued;
  }
}

function statusTone(status: string): string {
  switch (status.toLowerCase()) {
    case "ready":
      return "success";
    case "analyzing":
      return "warning";
    case "error":
      return "danger";
    default:
      return "neutral";
  }
}

export default function App() {
  const [language, setLanguage] = useState<Language>(() => {
    if (typeof window === "undefined") {
      return "sk";
    }

    const saved = window.localStorage.getItem("mixerai-language");
    return saved === "en" || saved === "sk" ? saved : "sk";
  });
  const t = copy[language];

  const [session, setSession] = useState<SessionResponse | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authForm, setAuthForm] = useState<AuthFormState>({ email: "", password: "" });
  const [authPending, setAuthPending] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const [workspace, setWorkspace] = useState<WorkspaceSnapshot | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [selectedDeckAId, setSelectedDeckAId] = useState("");
  const [selectedDeckBId, setSelectedDeckBId] = useState("");
  const [crossfader, setCrossfader] = useState(50);
  const [renderPending, setRenderPending] = useState(false);

  const [recommendationForm, setRecommendationForm] = useState<TransitionRecommendationRequest>({
    leftSetId: "",
    rightSetId: "",
    topK: 5,
  });
  const [recommendationPending, setRecommendationPending] = useState(false);
  const [recommendationError, setRecommendationError] = useState<string | null>(null);
  const [recommendationResults, setRecommendationResults] = useState<TransitionRecommendation[]>([]);

  const [analysisTrackA, setAnalysisTrackA] = useState<File | null>(null);
  const [analysisTrackB, setAnalysisTrackB] = useState<File | null>(null);
  const [analysisPending, setAnalysisPending] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<MixAnalysisResult | null>(null);

  const deckAAudioRef = useRef<HTMLAudioElement | null>(null);
  const deckBAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    window.localStorage.setItem("mixerai-language", language);
  }, [language]);

  useEffect(() => {
    let active = true;

    const loadSession = async () => {
      try {
        const currentSession = await api.getSession();
        if (active) {
          setSession(currentSession);
        }
      } catch {
        if (active) {
          setSession({ isAuthenticated: false, displayName: null, email: null });
        }
      } finally {
        if (active) {
          setSessionLoading(false);
        }
      }
    };

    void loadSession();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!session?.isAuthenticated) {
      setWorkspace(null);
      return;
    }

    void refreshWorkspace();
  }, [session?.isAuthenticated]);

  useEffect(() => {
    if (!workspace) {
      return;
    }

    const readyTracks = workspace.tracks.filter((track) => track.status.toLowerCase() === "ready");
    if (!selectedDeckAId && readyTracks[0]) {
      setSelectedDeckAId(readyTracks[0].id);
    }

    if (!selectedDeckBId && readyTracks[1]) {
      setSelectedDeckBId(readyTracks[1].id);
    }

    if (!recommendationForm.leftSetId && workspace.availableSetIds[0]) {
      setRecommendationForm({
        leftSetId: workspace.availableSetIds[0],
        rightSetId: workspace.availableSetIds[1] ?? workspace.availableSetIds[0],
        topK: 5,
      });
    }
  }, [workspace, selectedDeckAId, selectedDeckBId, recommendationForm.leftSetId]);

  useEffect(() => {
    if (deckAAudioRef.current) {
      deckAAudioRef.current.volume = (100 - crossfader) / 100;
    }

    if (deckBAudioRef.current) {
      deckBAudioRef.current.volume = crossfader / 100;
    }
  }, [crossfader, selectedDeckAId, selectedDeckBId]);

  async function refreshWorkspace() {
    setWorkspaceLoading(true);
    setWorkspaceError(null);

    try {
      const snapshot = await api.getWorkspace();
      startTransition(() => setWorkspace(snapshot));
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : language === "sk" ? "Workspace sa nepodarilo načítať." : "Workspace could not be loaded.");
    } finally {
      setWorkspaceLoading(false);
    }
  }

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthPending(true);
    setAuthError(null);

    try {
      const nextSession = authMode === "login"
        ? await api.login(authForm.email, authForm.password)
        : await api.register(authForm.email, authForm.password);

      setSession(nextSession);
      setNotice(authMode === "login"
        ? language === "sk" ? "Prihlásenie úspešné. Štúdio je pripravené." : "Signed in. Your studio is ready."
        : language === "sk" ? "Účet bol vytvorený. Štúdio je pripravené na demo." : "Account created. The studio is ready for your demo.");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : language === "sk" ? "Autentifikácia zlyhala." : "Authentication failed.");
    } finally {
      setAuthPending(false);
    }
  }

  async function handleLogout() {
    await api.logout();
    setSession({ isAuthenticated: false, displayName: null, email: null });
    setWorkspace(null);
    setNotice(language === "sk" ? "Odhlásil si sa zo štúdia." : "Signed out of the studio.");
  }

  async function handleUploadTrack(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      await api.uploadTrack(file);
      setNotice(language === "sk"
        ? `Track ${file.name} bol nahratý. Analýza sa zaradila do fronty.`
        : `Uploaded ${file.name}. Analysis will process it next.`);
      await refreshWorkspace();
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : language === "sk" ? "Upload zlyhal." : "Upload failed.");
    } finally {
      event.target.value = "";
    }
  }

  async function handleDeleteTrack(track: Track) {
    const message = language === "sk"
      ? `Vymazať "${track.title}" z knižnice?`
      : `Delete "${track.title}" from the library?`;

    if (!window.confirm(message)) {
      return;
    }

    try {
      await api.deleteTrack(track.id);
      setNotice(language === "sk" ? `Track ${track.title} bol odstránený.` : `Deleted ${track.title}.`);
      await refreshWorkspace();
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : language === "sk" ? "Mazanie zlyhalo." : "Delete failed.");
    }
  }

  async function handleRetryTrack(track: Track) {
    try {
      await api.retryTrackAnalysis(track.id);
      setNotice(language === "sk"
        ? `Analýza tracku ${track.title} bola znovu zaradená do fronty.`
        : `Analysis re-queued for ${track.title}.`);
      await refreshWorkspace();
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : language === "sk" ? "Opätovné spustenie zlyhalo." : "Retry failed.");
    }
  }

  async function handleRenderMix() {
    if (!selectedDeckAId || !selectedDeckBId) {
      setWorkspaceError(language === "sk" ? "Pred renderom vyber track pre oba decky." : "Select a track for both decks before rendering.");
      return;
    }

    setRenderPending(true);
    setWorkspaceError(null);
    try {
      const blob = await api.renderMix(selectedDeckAId, selectedDeckBId);
      triggerDownload(blob, "mixerai-auto-mix-reference.mp3");
      setNotice(language === "sk" ? "Automatický mix bol vygenerovaný a stiahnutý." : "Automatic mix generated and downloaded.");
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : language === "sk" ? "Render mixu zlyhal." : "Mix render failed.");
    } finally {
      setRenderPending(false);
    }
  }

  async function handleRecommendationSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRecommendationPending(true);
    setRecommendationError(null);

    try {
      setRecommendationResults(await api.recommendTransitions(recommendationForm));
    } catch (error) {
      setRecommendationError(error instanceof Error ? error.message : language === "sk" ? "Odporúčania sa nepodarilo získať." : "Recommendations failed.");
    } finally {
      setRecommendationPending(false);
    }
  }

  async function handleAnalyzeMix(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!analysisTrackA || !analysisTrackB) {
      setAnalysisError(language === "sk" ? "Pred AI analýzou je potrebné vybrať oba tracky." : "Choose both tracks before requesting AI analysis.");
      return;
    }

    setAnalysisPending(true);
    setAnalysisError(null);
    try {
      const result = await api.analyzeMix(analysisTrackA, analysisTrackB);
      setAnalysisResult(result);
      setNotice(language === "sk"
        ? "Analýza hotová. Získal si BPM, beat markery a odporúčaný overlay timing."
        : "Analysis completed with BPM, beat markers and a suggested overlay window.");
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : language === "sk" ? "Analýza zlyhala." : "Analysis failed.");
    } finally {
      setAnalysisPending(false);
    }
  }

  const readyTracks = workspace?.tracks.filter((track) => track.status.toLowerCase() === "ready") ?? [];
  const selectedTrackA = workspace?.tracks.find((track) => track.id === selectedDeckAId) ?? null;
  const selectedTrackB = workspace?.tracks.find((track) => track.id === selectedDeckBId) ?? null;
  const deckAWaveform = parseWaveform(selectedTrackA);
  const deckBWaveform = parseWaveform(selectedTrackB);
  const advice = buildAdvice(selectedTrackA, selectedTrackB, language);
  const tips = buildTips(selectedTrackA, selectedTrackB, language);
  const profileName = workspace?.displayName ?? session?.displayName ?? session?.email ?? t.studioTitle;
  const languageSwitcher = (
    <div className="language-switch" role="group" aria-label={t.language}>
      {(["sk", "en"] as const).map((option) => (
        <button
          key={option}
          type="button"
          className={language === option ? "language-button active" : "language-button"}
          onClick={() => setLanguage(option)}
        >
          {option.toUpperCase()}
        </button>
      ))}
    </div>
  );

  if (sessionLoading) {
    return (
      <div className="app-state-screen">
        <div className="state-card">
          <p className="eyebrow">MixerAI</p>
          <h1>{t.loadingTitle}</h1>
          <p>{t.loadingBody}</p>
        </div>
      </div>
    );
  }

  if (!session?.isAuthenticated) {
    return (
      <div className="app-shell landing-shell">
        <header className="topbar">
          <div className="brand-block">
            <p className="eyebrow">{t.landingEyebrow}</p>
            <h1 className="brand-title">{t.studioTitle}</h1>
            <p className="brand-subtitle">{t.landingBody}</p>
          </div>
          <div className="topbar-meta">
            <div className="tag-row">
              {techPills.map((pill) => (
                <span key={pill} className="tag">{pill}</span>
              ))}
            </div>
            {languageSwitcher}
          </div>
        </header>

        <main className="landing-grid">
          <section className="hero-card hero-card-landing">
            <p className="product-badge">{language === "sk" ? "Produkt + portfolio" : "Product + portfolio"}</p>
            <h2>{t.landingTitle}</h2>
            <p className="hero-copy">{t.landingBody}</p>
            <div className="journey-grid">
              {t.landingCards.map(([title, body]) => (
                <article key={title} className="journey-card">
                  <strong>{title}</strong>
                  <span>{body}</span>
                </article>
              ))}
            </div>
            <div className="feature-grid">
              {t.landingFeatures.map(([title, body]) => (
                <article key={title} className="feature-card">
                  <strong>{title}</strong>
                  <span>{body}</span>
                </article>
              ))}
            </div>
          </section>

          <section className="auth-card">
            <div className="section-copy">
              <p className="eyebrow">{t.authTitle}</p>
              <h3>{t.studioTitle}</h3>
              <p className="muted-copy">{t.authBody}</p>
            </div>
            <div className="toggle-row">
              <button type="button" className={authMode === "login" ? "segmented-button active" : "segmented-button"} onClick={() => setAuthMode("login")}>
                {t.signIn}
              </button>
              <button type="button" className={authMode === "register" ? "segmented-button active" : "segmented-button"} onClick={() => setAuthMode("register")}>
                {t.createAccount}
              </button>
            </div>
            <form className="stack-form" onSubmit={handleAuthSubmit}>
              <label className="field">
                <span>{t.email}</span>
                <input
                  value={authForm.email}
                  onChange={(event) => setAuthForm((current) => ({ ...current, email: event.target.value }))}
                  type="email"
                  placeholder="dj@example.com"
                  required
                />
              </label>
              <label className="field">
                <span>{t.password}</span>
                <input
                  value={authForm.password}
                  onChange={(event) => setAuthForm((current) => ({ ...current, password: event.target.value }))}
                  type="password"
                  placeholder={t.passwordPlaceholder}
                  required
                />
              </label>
              {authError ? <div className="inline-message danger">{authError}</div> : null}
              <button type="submit" className="primary-button" disabled={authPending}>
                {authPending ? t.working : authMode === "login" ? t.openWorkspace : t.createDemoAccount}
              </button>
            </form>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <p className="eyebrow">{t.topbarEyebrow}</p>
          <h1 className="brand-title">{t.studioTitle}</h1>
          <p className="brand-subtitle">{t.heroBody}</p>
        </div>
        <div className="topbar-actions">
          <div className="signed-in-panel">
            <span className="signed-in-label">{t.signedInAs}</span>
            <strong>{session.displayName ?? session.email}</strong>
          </div>
          {languageSwitcher}
          <button type="button" className="secondary-button" onClick={() => void refreshWorkspace()} disabled={workspaceLoading}>
            {workspaceLoading ? t.refreshing : t.refresh}
          </button>
          <button type="button" className="ghost-button" onClick={() => void handleLogout()}>
            {t.signOut}
          </button>
        </div>
      </header>

      <main className="dashboard-shell">
        <section className="hero-banner">
          <div className="hero-banner-copy">
            <p className="eyebrow">{t.landingEyebrow}</p>
            <h2>{t.heroTitle(profileName)}</h2>
            <p className="hero-copy">{t.heroBody}</p>
            <div className="journey-grid">
              {t.heroCards.map(([title, body]) => (
                <article key={title} className="journey-card">
                  <strong>{title}</strong>
                  <span>{body}</span>
                </article>
              ))}
            </div>
          </div>
          <div className="hero-side">
            <div className="metric-grid">
              <article className="metric-card"><span>{t.readyTracks}</span><strong>{workspace?.readyTrackCount ?? 0}</strong></article>
              <article className="metric-card"><span>{t.needsAttention}</span><strong>{workspace?.failedTrackCount ?? 0}</strong></article>
              <article className="metric-card"><span>{t.referenceSets}</span><strong>{workspace?.availableSetIds.length ?? 0}</strong></article>
            </div>
            <article className="spotlight-card">
              <p className="eyebrow">{t.stackTitle}</p>
              <p className="muted-copy">{t.stackBody}</p>
              <div className="tag-row">
                {techPills.map((pill) => (
                  <span key={pill} className="tag">{pill}</span>
                ))}
              </div>
            </article>
          </div>
        </section>

        {notice ? <div className="inline-message success">{notice}</div> : null}
        {workspaceError ? <div className="inline-message danger">{workspaceError}</div> : null}

        <section className="dashboard-grid dashboard-grid-main">
          <article className="panel panel-large">
            <div className="panel-header">
              <div className="section-copy">
                <p className="eyebrow">{t.mixCoach}</p>
                <h3>{t.mixCoachTitle}</h3>
                <p className="muted-copy">{t.mixCoachBody}</p>
              </div>
            </div>
            {readyTracks.length < 2 ? <div className="inline-message info">{t.mixCoachEmpty}</div> : null}
            <div className="deck-grid">
              <div className="deck-card deck-a">
                <div className="deck-header">
                  <span className="deck-label">{t.deckA}</span>
                  <select value={selectedDeckAId} onChange={(event) => setSelectedDeckAId(event.target.value)}>
                    <option value="">{t.chooseTrack}</option>
                    {readyTracks.map((track) => (
                      <option key={track.id} value={track.id}>{track.title}</option>
                    ))}
                  </select>
                </div>
                <strong>{selectedTrackA?.title ?? t.noTrack}</strong>
                <p className="deck-subcopy">{selectedTrackA?.artist ?? t.noArtist}</p>
                <div className="deck-meta">
                  <span>{selectedTrackA?.bpm ? `${selectedTrackA.bpm.toFixed(1)} BPM` : "-- BPM"}</span>
                  <span>{selectedTrackA?.camelotKey ?? "--"}</span>
                  <span>{formatDuration(selectedTrackA?.durationSeconds ?? 0)}</span>
                </div>
                <WaveformCanvas className="waveform" samples={deckAWaveform} accent="#ff9b54" />
                <audio ref={deckAAudioRef} controls src={selectedTrackA ? `/api/bff/library/audio/${selectedTrackA.id}` : undefined} />
              </div>

              <div className="deck-card deck-b">
                <div className="deck-header">
                  <span className="deck-label">{t.deckB}</span>
                  <select value={selectedDeckBId} onChange={(event) => setSelectedDeckBId(event.target.value)}>
                    <option value="">{t.chooseTrack}</option>
                    {readyTracks.map((track) => (
                      <option key={track.id} value={track.id}>{track.title}</option>
                    ))}
                  </select>
                </div>
                <strong>{selectedTrackB?.title ?? t.noTrack}</strong>
                <p className="deck-subcopy">{selectedTrackB?.artist ?? t.noArtist}</p>
                <div className="deck-meta">
                  <span>{selectedTrackB?.bpm ? `${selectedTrackB.bpm.toFixed(1)} BPM` : "-- BPM"}</span>
                  <span>{selectedTrackB?.camelotKey ?? "--"}</span>
                  <span>{formatDuration(selectedTrackB?.durationSeconds ?? 0)}</span>
                </div>
                <WaveformCanvas className="waveform" samples={deckBWaveform} accent="#59b8ff" />
                <audio ref={deckBAudioRef} controls src={selectedTrackB ? `/api/bff/library/audio/${selectedTrackB.id}` : undefined} />
              </div>
            </div>

            <div className="crossfader-panel">
              <div className="crossfader-copy">
                <strong>{t.crossfaderTitle}</strong>
                <span>{t.crossfaderBody}</span>
              </div>
              <input type="range" min="0" max="100" value={crossfader} onChange={(event) => setCrossfader(Number(event.target.value))} />
            </div>

            <div className="coach-bar">
              <div className="section-copy">
                <p className="eyebrow">{t.adviceTitle}</p>
                <p className="muted-copy">{t.renderHint}</p>
              </div>
              <button type="button" className="primary-button" onClick={() => void handleRenderMix()} disabled={renderPending}>
                {renderPending ? t.renderingMix : t.renderMix}
              </button>
            </div>

            <div className="advice-list">
              {advice.map((item) => (
                <p key={item}>{item}</p>
              ))}
            </div>
          </article>

          <div className="stack-column">
            <article className="panel">
              <div className="panel-header">
                <div className="section-copy">
                  <p className="eyebrow">{t.planner}</p>
                  <h3>{t.plannerTitle}</h3>
                  <p className="muted-copy">{t.plannerBody}</p>
                </div>
              </div>
              <form className="stack-form" onSubmit={handleRecommendationSubmit}>
                <label className="field">
                  <span>{t.leftSet}</span>
                  <select value={recommendationForm.leftSetId} onChange={(event) => setRecommendationForm((current) => ({ ...current, leftSetId: event.target.value }))}>
                    <option value="">{t.chooseSet}</option>
                    {workspace?.availableSetIds.map((setId) => (
                      <option key={setId} value={setId}>{setId}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>{t.rightSet}</span>
                  <select value={recommendationForm.rightSetId} onChange={(event) => setRecommendationForm((current) => ({ ...current, rightSetId: event.target.value }))}>
                    <option value="">{t.chooseSet}</option>
                    {workspace?.availableSetIds.map((setId) => (
                      <option key={setId} value={setId}>{setId}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>{t.topCandidates}</span>
                  <input type="number" min="1" max="20" value={recommendationForm.topK} onChange={(event) => setRecommendationForm((current) => ({ ...current, topK: Number(event.target.value) }))} />
                </label>
                {recommendationError ? <div className="inline-message danger">{recommendationError}</div> : null}
                <button type="submit" className="secondary-button" disabled={recommendationPending}>
                  {recommendationPending ? t.findingCues : t.findCues}
                </button>
              </form>
              <div className="result-list">
                {recommendationResults.length === 0 ? (
                  <p className="muted-copy">{t.noRecommendations}</p>
                ) : (
                  recommendationResults.map((result) => (
                    <article key={`${result.leftSetId}-${result.rightSetId}-${result.leftSegmentIndex}-${result.rightSegmentIndex}`} className="result-card">
                      <div><strong>{result.leftSetId}</strong><span>{result.leftStartSeconds.toFixed(1)}s</span></div>
                      <span className="arrow">→</span>
                      <div><strong>{result.rightSetId}</strong><span>{result.rightStartSeconds.toFixed(1)}s</span></div>
                      <div className="score"><span>{t.fit}</span><strong>{(result.probability * 100).toFixed(1)}%</strong></div>
                    </article>
                  ))
                )}
              </div>
            </article>
            <article className="panel">
              <div className="panel-header">
                <div className="section-copy">
                  <p className="eyebrow">{t.basics}</p>
                  <h3>{t.basicsTitle}</h3>
                  <p className="muted-copy">{t.basicsBody}</p>
                </div>
              </div>
              <div className="learning-list">
                {tips.map((tip) => (
                  <article key={tip} className="tip-card"><p>{tip}</p></article>
                ))}
              </div>
            </article>
          </div>
        </section>

        <section className="dashboard-grid dashboard-grid-secondary">
          <article className="panel">
            <div className="panel-header">
              <div className="section-copy">
                <p className="eyebrow">{t.analyzer}</p>
                <h3>{t.analyzerTitle}</h3>
                <p className="muted-copy">{t.analyzerBody}</p>
              </div>
            </div>
            <form className="stack-form" onSubmit={handleAnalyzeMix}>
              <label className="field">
                <span>{t.deckA}</span>
                <input type="file" accept=".mp3,.wav,.flac,.m4a,.ogg,.mp4" onChange={(event) => setAnalysisTrackA(event.target.files?.[0] ?? null)} />
              </label>
              <label className="field">
                <span>{t.deckB}</span>
                <input type="file" accept=".mp3,.wav,.flac,.m4a,.ogg,.mp4" onChange={(event) => setAnalysisTrackB(event.target.files?.[0] ?? null)} />
              </label>
              {analysisError ? <div className="inline-message danger">{analysisError}</div> : null}
              <button type="submit" className="secondary-button" disabled={analysisPending}>
                {analysisPending ? t.analyzing : t.analyze}
              </button>
            </form>

            {analysisResult ? (
              <div className="analysis-grid">
                <div className="metric-grid">
                  <article className="metric-card"><span>{t.trackABpm}</span><strong>{analysisResult.recommendation.leftBpm.toFixed(2)}</strong></article>
                  <article className="metric-card"><span>{t.trackBBpm}</span><strong>{analysisResult.recommendation.rightBpm.toFixed(2)}</strong></article>
                  <article className="metric-card"><span>{t.overlayStart}</span><strong>{analysisResult.recommendation.overlayStartSeconds.toFixed(2)}s</strong></article>
                  <article className="metric-card"><span>{t.modelConfidence}</span><strong>{(analysisResult.recommendation.probability * 100).toFixed(1)}%</strong></article>
                </div>
                <div className="analysis-track">
                  <div className="analysis-track-header">
                    <strong>{analysisResult.trackA.label || t.deckA}</strong>
                    <span>{t.previewLength(`${analysisResult.trackA.previewDurationSeconds.toFixed(2)}s`)}</span>
                  </div>
                  <WaveformCanvas className="waveform waveform-tall" samples={analysisResult.trackA.waveform} accent="#ffd36b" beatMarkers={analysisResult.trackA.beatMarkers} durationSeconds={analysisResult.trackA.previewDurationSeconds} />
                </div>
                <div className="analysis-track">
                  <div className="analysis-track-header">
                    <strong>{analysisResult.trackB.label || t.deckB}</strong>
                    <span>{t.suggestedSource(`${analysisResult.recommendation.rightStartSeconds.toFixed(2)}s`)}</span>
                  </div>
                  <WaveformCanvas className="waveform waveform-tall" samples={analysisResult.trackB.waveform} accent="#6bc5ff" beatMarkers={analysisResult.trackB.beatMarkers} durationSeconds={analysisResult.trackB.previewDurationSeconds} />
                </div>
              </div>
            ) : (
              <p className="muted-copy">{t.analyzerEmpty}</p>
            )}
          </article>
        </section>

        <section className="dashboard-grid">
          <article className="panel">
            <div className="panel-header">
              <div className="section-copy">
                <p className="eyebrow">{t.library}</p>
                <h3>{t.libraryTitle}</h3>
                <p className="muted-copy">{t.libraryBody}</p>
              </div>
              <label className="upload-button">
                {t.uploadAudio}
                <input type="file" accept=".mp3,.wav,.flac,.m4a,.ogg,.mp4" onChange={handleUploadTrack} />
              </label>
            </div>
            <div className="table-shell">
              <table className="track-table">
                <thead>
                  <tr>{t.table.map((label) => <th key={label}>{label}</th>)}</tr>
                </thead>
                <tbody>
                  {workspace?.tracks.length ? (
                    workspace.tracks.map((track) => (
                      <tr key={track.id}>
                        <td><span className={`status-pill ${statusTone(track.status)}`}>{statusLabel(track.status, t)}</span></td>
                        <td>
                          <div className="title-cell">
                            <strong>{track.title}</strong>
                            <span>{track.lastAnalysisError ?? track.artist ?? t.noArtist}</span>
                          </div>
                        </td>
                        <td>{track.bpm ? track.bpm.toFixed(1) : "--"}</td>
                        <td>{track.camelotKey ?? "--"}</td>
                        <td>{formatDuration(track.durationSeconds)}</td>
                        <td>{track.analysisAttempts}</td>
                        <td>{formatDate(track.createdAtUtc, language)}</td>
                        <td>
                          <div className="button-row compact">
                            <button type="button" className="tiny-button" onClick={() => setSelectedDeckAId(track.id)} disabled={track.status.toLowerCase() !== "ready"}>{t.deckA}</button>
                            <button type="button" className="tiny-button blue" onClick={() => setSelectedDeckBId(track.id)} disabled={track.status.toLowerCase() !== "ready"}>{t.deckB}</button>
                            {track.status.toLowerCase() === "error" ? (
                              <button type="button" className="tiny-button gold" onClick={() => void handleRetryTrack(track)}>{t.retry}</button>
                            ) : null}
                            <button type="button" className="tiny-button danger" onClick={() => void handleDeleteTrack(track)}>{t.delete}</button>
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan={8} className="empty-table">{t.emptyTable}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </article>
        </section>
      </main>
    </div>
  );
}
