"""Tandem API: vendor-neutral music agent and WAV analysis/tuning."""
import io, json, os, re, wave
from pathlib import Path
from typing import Any, Literal
import httpx
import numpy as np
from scipy import signal
from world_tuning import world_tune
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from request_guards import RequestGuardMiddleware, AUDIO_BODY_MAX_BYTES, LOCAL_AUDIO_BODY_MAX_BYTES, is_local

app = FastAPI(title="Tandem API", version="0.2.0")

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Report where and why validation failed without echoing the input back: echoed
    # values can be large, and NaN/Infinity cannot be serialized as JSON at all.
    errors=[{"loc":list(e.get("loc",()))[:8],"msg":str(e.get("msg",""))[:200],"type":e.get("type","")} for e in exc.errors()[:20]]
    return JSONResponse(status_code=422,content={"detail":errors})

@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(Path(__file__).resolve().parent / "index.html", media_type="text/html")

@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(Path(__file__).resolve().parent / "sw.js", media_type="text/javascript")

@app.get("/history.js", include_in_schema=False)
def history_js():
    return FileResponse(Path(__file__).resolve().parent / "history.js", media_type="text/javascript")

@app.get("/groove.js", include_in_schema=False)
def groove_js():
    return FileResponse(Path(__file__).resolve().parent / "groove.js", media_type="text/javascript")
@app.get("/storage.js", include_in_schema=False)
def storage_js():
    return FileResponse(Path(__file__).resolve().parent / "storage.js", media_type="text/javascript")
@app.get("/samples.js", include_in_schema=False)
def samples_js():
    return FileResponse(Path(__file__).resolve().parent / "samples.js", media_type="text/javascript")

@app.get("/recordings.js", include_in_schema=False)
def recordings_js():
    return FileResponse(Path(__file__).resolve().parent / "recordings.js", media_type="text/javascript")


@app.get("/phrases.js", include_in_schema=False)
def phrases_js():
    return FileResponse(Path(__file__).resolve().parent / "phrases.js", media_type="text/javascript")
@app.get("/harmony.js", include_in_schema=False)
def harmony_js():
    return FileResponse(Path(__file__).resolve().parent / "harmony.js", media_type="text/javascript")
@app.get("/voices.js", include_in_schema=False)
def voices_js():
    return FileResponse(Path(__file__).resolve().parent / "voices.js", media_type="text/javascript")
@app.get("/versions.js", include_in_schema=False)
def versions_js():
    return FileResponse(Path(__file__).resolve().parent / "versions.js", media_type="text/javascript")

@app.get("/contour.js", include_in_schema=False)
def contour_js():
    return FileResponse(Path(__file__).resolve().parent / "contour.js", media_type="text/javascript")

@app.get("/polish.js", include_in_schema=False)
def polish_js():
    return FileResponse(Path(__file__).resolve().parent / "polish.js", media_type="text/javascript")

@app.get("/tuning.js", include_in_schema=False)
def tuning_js():
    return FileResponse(Path(__file__).resolve().parent / "tuning.js", media_type="text/javascript")

@app.get("/transcription.js", include_in_schema=False)
def transcription_script():
    return FileResponse(Path(__file__).resolve().parent / "transcription.js", media_type="text/javascript")

# Self-hosted Spotify Basic Pitch (SEC.3): the bundle and model are built by
# tools/basic-pitch/build.sh and their SHA-256 hashes are in SHA256SUMS. Only
# these exact files are served; the versioned path never changes content, so
# browsers may cache it forever.
BASIC_PITCH_DIR = Path(__file__).resolve().parent / "vendor" / "basic-pitch-1.0.1"
BASIC_PITCH_FILES = {
    "basic-pitch.mjs": "text/javascript",
    "model/model.json": "application/json",
    "model/group1-shard1of1.bin": "application/octet-stream",
}

@app.get("/vendor/basic-pitch-1.0.1/{name:path}", include_in_schema=False)
def basic_pitch_asset(name: str):
    media_type = BASIC_PITCH_FILES.get(name)
    if media_type is None:
        return Response(status_code=404)
    return FileResponse(BASIC_PITCH_DIR / name, media_type=media_type,
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

# Self-hosted General MIDI instrument samples (SND.1), rendered from the MIT-licensed FluidR3_GM
# SoundFont by tools/gm-samples/build.py. Only the files listed in SHA256SUMS are served (the
# list itself is not); like Basic Pitch, the versioned path never changes content.
GM_SAMPLES_DIR = Path(__file__).resolve().parent / "vendor" / "gm-samples-1"
GM_SAMPLE_TYPES = {".mp3": "audio/mpeg", ".json": "application/json", ".txt": "text/plain; charset=utf-8"}
GM_SAMPLE_FILES = {
    name: GM_SAMPLE_TYPES[Path(name).suffix]
    for name in (line.split("  ", 1)[1] for line in (GM_SAMPLES_DIR / "SHA256SUMS").read_text().splitlines() if line)
}

@app.get("/vendor/gm-samples-1/{name:path}", include_in_schema=False)
def gm_sample(name: str):
    media_type = GM_SAMPLE_FILES.get(name)
    if media_type is None:
        return Response(status_code=404)
    return FileResponse(GM_SAMPLES_DIR / name, media_type=media_type,
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

# VOX.4: the WORLD vocoder compiled to WebAssembly by tools/world-wasm/build.sh, for tuning on the
# device. Only the files listed in SHA256SUMS are served; the versioned path never changes content.
WORLD_WASM_DIR = Path(__file__).resolve().parent / "vendor" / "world-d625e76-1"
WORLD_WASM_FILES = {"world.mjs": "text/javascript", "world.wasm": "application/wasm", "LICENSES.txt": "text/plain; charset=utf-8"}

@app.get("/vendor/world-d625e76-1/{name}", include_in_schema=False)
def world_wasm_asset(name: str):
    media_type = WORLD_WASM_FILES.get(name)
    if media_type is None:
        return Response(status_code=404)
    return FileResponse(WORLD_WASM_DIR / name, media_type=media_type,
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

# MOB.2: the app icons, rendered from icons/*.svg by tools/icons/build.py. Only the built PNGs are served.
ICONS_DIR = Path(__file__).resolve().parent / "icons"
ICON_FILES = {"icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"}

@app.get("/icons/{name}", include_in_schema=False)
def app_icon(name: str):
    if name not in ICON_FILES:
        return Response(status_code=404)
    return FileResponse(ICONS_DIR / name, media_type="image/png")

# MOB.1: the phone capture page, its module and its own manifest (so adding it to the home screen opens capture).
@app.get("/capture", include_in_schema=False)
def capture_page():
    return FileResponse(Path(__file__).resolve().parent / "capture.html", media_type="text/html")

@app.get("/bundle.js", include_in_schema=False)
def bundle_js():
    return FileResponse(Path(__file__).resolve().parent / "bundle.js", media_type="text/javascript")

@app.get("/daw.js", include_in_schema=False)
def daw_js():
    return FileResponse(Path(__file__).resolve().parent / "daw.js", media_type="text/javascript")

@app.get("/notation.js", include_in_schema=False)
def notation_js():
    return FileResponse(Path(__file__).resolve().parent / "notation.js", media_type="text/javascript")

@app.get("/dawproject.js", include_in_schema=False)
def dawproject_js():
    return FileResponse(Path(__file__).resolve().parent / "dawproject.js", media_type="text/javascript")

@app.get("/midi.js", include_in_schema=False)
def midi_js():
    return FileResponse(Path(__file__).resolve().parent / "midi.js", media_type="text/javascript")

@app.get("/noteedit.js", include_in_schema=False)
def noteedit_js():
    return FileResponse(Path(__file__).resolve().parent / "noteedit.js", media_type="text/javascript")

@app.get("/guide.js", include_in_schema=False)
def guide_js():
    return FileResponse(Path(__file__).resolve().parent / "guide.js", media_type="text/javascript")

@app.get("/playhead.js", include_in_schema=False)
def playhead_js():
    return FileResponse(Path(__file__).resolve().parent / "playhead.js", media_type="text/javascript")

@app.get("/evolution.js", include_in_schema=False)
def evolution_js():
    return FileResponse(Path(__file__).resolve().parent / "evolution.js", media_type="text/javascript")

@app.get("/take.js", include_in_schema=False)
def take_js():
    return FileResponse(Path(__file__).resolve().parent / "take.js", media_type="text/javascript")


@app.get("/pitch.js", include_in_schema=False)
def pitch_js():
    return FileResponse(Path(__file__).resolve().parent / "pitch.js", media_type="text/javascript")


@app.get("/beats.js", include_in_schema=False)
def beats_js():
    return FileResponse(Path(__file__).resolve().parent / "beats.js", media_type="text/javascript")


@app.get("/mixer.js", include_in_schema=False)
def mixer_js():
    return FileResponse(Path(__file__).resolve().parent / "mixer.js", media_type="text/javascript")
@app.get("/takes.js", include_in_schema=False)
def takes_js():
    return FileResponse(Path(__file__).resolve().parent / "takes.js", media_type="text/javascript")
@app.get("/genre.js", include_in_schema=False)
def genre_js():
    return FileResponse(Path(__file__).resolve().parent / "genre.js", media_type="text/javascript")
@app.get("/lyrics.js", include_in_schema=False)
def lyrics_js():
    return FileResponse(Path(__file__).resolve().parent / "lyrics.js", media_type="text/javascript")

@app.get("/tension.js", include_in_schema=False)
def tension_js():
    return FileResponse(Path(__file__).resolve().parent / "tension.js", media_type="text/javascript")

@app.get("/drawline.js", include_in_schema=False)
def drawline_js():
    return FileResponse(Path(__file__).resolve().parent / "drawline.js", media_type="text/javascript")

@app.get("/practice.js", include_in_schema=False)
def practice_js():
    return FileResponse(Path(__file__).resolve().parent / "practice.js", media_type="text/javascript")

@app.get("/sections.js", include_in_schema=False)
def sections_js():
    return FileResponse(Path(__file__).resolve().parent / "sections.js", media_type="text/javascript")

@app.get("/layers.js", include_in_schema=False)
def layers_js():
    return FileResponse(Path(__file__).resolve().parent / "layers.js", media_type="text/javascript")
@app.get("/latency.js", include_in_schema=False)
def latency_js():
    return FileResponse(Path(__file__).resolve().parent / "latency.js", media_type="text/javascript")


@app.get("/worldtune.js", include_in_schema=False)
def worldtune_js():
    return FileResponse(Path(__file__).resolve().parent / "worldtune.js", media_type="text/javascript")

@app.get("/tuneworker.js", include_in_schema=False)
def tuneworker_js():
    return FileResponse(Path(__file__).resolve().parent / "tuneworker.js", media_type="text/javascript")

@app.get("/ideas.js", include_in_schema=False)
def ideas_js():
    return FileResponse(Path(__file__).resolve().parent / "ideas.js", media_type="text/javascript")

@app.get("/capture.webmanifest", include_in_schema=False)
def capture_manifest():
    return FileResponse(Path(__file__).resolve().parent / "capture.webmanifest", media_type="application/manifest+json")

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(Path(__file__).resolve().parent / "manifest.webmanifest", media_type="application/manifest+json")

origins = [x.strip() for x in os.getenv("TANDEM_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,https://ogoldberg.github.io").split(",") if x.strip()]
# Added before CORS so CORS stays outermost and 413/429/503 guard responses carry CORS headers.
app.add_middleware(RequestGuardMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST","PUT","DELETE"], allow_headers=["*"])
@app.middleware("http")
async def authenticate(req: Request, call_next):
    if req.url.path == "/api/chat":
        secret=os.getenv("TANDEM_ACCESS_TOKEN", "")
        if os.getenv("VERCEL") and not secret:
            return Response('{"detail":"Set TANDEM_ACCESS_TOKEN in Vercel to protect AI spending"}',status_code=503,media_type="application/json")
        if secret and req.headers.get("x-tandem-token") != secret:
            return Response('{"detail":"Invalid Tandem access token"}',status_code=401,media_type="application/json")
    return await call_next(req)
# Per-request audio limits. The hosted limits keep each request inside Vercel's time and body
# limits (the browser splits longer takes into chunks); requests from the Mac app's own window
# (DESK.2, checked by tandem_desktop.guarded_app) tune and analyse up to 10 minutes at once.
HOSTED_LIMITS={"analyze_seconds":90,"tune_seconds":25,"tune_notes":128,"audio_bytes":AUDIO_BODY_MAX_BYTES}
LOCAL_LIMITS={"analyze_seconds":600,"tune_seconds":600,"tune_notes":4096,"audio_bytes":LOCAL_AUDIO_BODY_MAX_BYTES}
def limits_for(request: Request):
    return LOCAL_LIMITS if is_local(request.scope) else HOSTED_LIMITS
@app.get("/api/health")
def health(): return {"ok":True,"version":"0.2.0"}
def env_llm_config():
    """The server's own AI configuration (the hosted mode's operator key, or a developer's env)."""
    return {"provider":os.getenv("TANDEM_PROVIDER","openai-compatible").lower(),"model":os.getenv("TANDEM_MODEL",""),
            "key":os.getenv("TANDEM_API_KEY",""),"base_url":os.getenv("TANDEM_BASE_URL","").rstrip("/")}
def llm_config(request: Request):
    """AI.4: in the Mac app's own window, the person's saved provider, model and Keychain key
    (scope["tandem_ai"], set only by tandem_desktop.guarded_app); otherwise, or when nothing is
    saved there, the server's own configuration. A saved choice that cannot be used is an error,
    never a silent switch to another provider."""
    saved=request.scope.get("tandem_ai") if is_local(request.scope) else None
    if saved is not None:
        try: config=saved.llm_config()
        except ValueError as exc: raise HTTPException(503,str(exc)[:300]) from exc
        if config is not None: return {**config,"source":"your-settings"}
        if not os.getenv("TANDEM_MODEL"): raise HTTPException(503,"Choose your AI provider and model in Your AI, under Compose together.")
    return {**env_llm_config(),"source":"server"}
@app.get("/api/health")
def health(): return {"ok":True,"version":"0.2.0"}
@app.get("/api/config")
def config(request: Request):
    try: llm=llm_config(request); ai_problem=""
    except HTTPException as exc: llm={**env_llm_config(),"model":"","source":"your-settings"}; ai_problem=exc.detail
    provider,model,ready=llm["provider"],llm["model"],bool(llm["model"])
    # MODEL.1: the Mac app's window is told which large models are installed; the hosted app has none.
    models=request.scope.get("tandem_models") if is_local(request.scope) else None
    return {"runtime":"desktop" if os.getenv("TANDEM_RUNTIME")=="desktop" else "web","models_installed":models.installed_ids() if models is not None else [],"limits":{k:v for k,v in limits_for(request).items() if k!="audio_bytes"},"provider":provider,"model":model,"ai_ready":ready,"ai_source":llm["source"],"ai_problem":ai_problem,"requires_token":bool(os.getenv("TANDEM_ACCESS_TOKEN")),"capabilities":{"conversation":{"provider":provider,"model":model,"enabled":ready},"melody_transcription":{"provider":"browser-basic-pitch","model":"spotify/basic-pitch-1.0.1","enabled":True},"rhythm_transcription":{"provider":"local-dsp","model":"onset-detector-v1","enabled":True},"vocal_polish":{"provider":"browser-dsp","model":"filter-gate-compressor-v1","enabled":True},"vocal_pitch_correction":{"provider":"open-source-world","model":"pyworld-prebuilt-0.3.6","enabled":True},"music_generation":{"provider":os.getenv("TANDEM_MUSIC_PROVIDER","none"),"model":os.getenv("TANDEM_MUSIC_MODEL",""),"enabled":False}}}

# Melody instruments the browser can play; must match INSTRUMENTS in voices.js (checked by tests/voices.test.mjs).
INSTRUMENTS = ("piano", "marimba", "strings", "bass", "chip", "organ", "guitar", "flute")
# GENRE.1: the optional genres (genre.js GENRES, same ids in the same order, which a Node test checks),
# each with the line of context the chat is given when the project has that genre.
GENRES={
    "pop":"The song is pop: catchy, simple chords (I, V, vi, IV), a steady straight beat.",
    "rock":"The song is rock: power chords, a driving straight beat with the snare on 2 and 4.",
    "folk":"The song is folk: acoustic, simple chords (I, IV, V), a gentle beat.",
    "jazz":"The song is jazz: seventh chords, ii-V-I movement, swung eighths and a walking bass.",
    "hiphop":"The song is hip-hop: a laid-back half-time beat, held chords and a deep bass, lightly swung sixteenths.",
    "electronic":"The song is electronic dance music: four on the floor, tight sixteenths, an octave bass.",
}
GENRE_IDS=tuple(GENRES)
class ProjectNote(BaseModel):
    model_config=ConfigDict(extra="forbid")
    m: int = Field(ge=0,le=127)
    t: float = Field(ge=0,le=600,allow_inf_nan=False)
    d: float = Field(gt=0,le=600,allow_inf_nan=False)
class ProjectHit(BaseModel):
    model_config=ConfigDict(extra="forbid")
    k: Literal["kick","snare","hat"]
    t: float = Field(ge=0,le=600,allow_inf_nan=False)
class ProjectBand(BaseModel):
    """GEN.2: the backing band generated in the Mac app. Its audio is a recording kept beside the project
    (the band slot), never in it; this records what made it. No AI action edits it. MRT.1: model
    mrt2_small (Magenta RealTime 2) plays the melody and harmony notes (follows "notes"), with its
    drums on or off; MusicGen-Melody follows the melody or the recording."""
    model_config=ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")
    style: str = Field(min_length=1,max_length=200)
    follows: Literal["melody","recording","notes"]
    seconds: float = Field(ge=1,le=30,allow_inf_nan=False)
    muted: bool = False
    model: Literal["musicgen-melody","mrt2_small"] = "musicgen-melody"
    drums: bool | None = Field(default=None,strict=True)
    @model_validator(mode="after")
    def _engine(self):
        if (self.model == "mrt2_small") != (self.follows == "notes"):
            raise ValueError("a band from the notes is made by mrt2_small, and only it follows the notes")
        if self.drums is not None and self.model != "mrt2_small":
            raise ValueError("only a band from the notes has its own drums setting")
        return self
class ProjectTimbre(BaseModel):
    """TIMBRE.1: the recorded voice played as an instrument by a RAVE model in the Mac app. Its audio is a
    recording kept beside the project (the timbre slot), never in it. No AI action edits it."""
    model_config=ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")
    instrument: Literal["sax","guitar","organ"]
    source: Literal["take","tuned"]
    seconds: float = Field(gt=0,le=600,allow_inf_nan=False)
    muted: bool = False
    model: Literal["rave"] = "rave"
class ProjectSungHarmony(BaseModel):
    """HARM.3: the take sung back on the harmony voice's notes with WORLD, in the studio. Its audio is a
    recording kept beside the project (the voice2_sung slot), never in it; line names the harmony line it
    was sung on (tuning.js harmonyFingerprint). No AI action edits it."""
    model_config=ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")
    seconds: float = Field(gt=0,le=600,allow_inf_nan=False)
    muted: bool = False
    line: str = Field(pattern=r"^[0-9a-f]{8}$")
class MixChannel(BaseModel):
    """MIX.1: one part's level in dB, mute and solo (mixer.js cleanMix)."""
    model_config=ConfigDict(extra="forbid")
    level: float = Field(default=0,ge=-30,le=6,allow_inf_nan=False)
    mute: bool | None = None
    solo: bool = False
class OwnMuteChannel(BaseModel):
    """MIX.1: the band, the voice as instrument and the sung harmony keep their mute in their own muted field."""
    model_config=ConfigDict(extra="forbid")
    level: float = Field(default=0,ge=-30,le=6,allow_inf_nan=False)
    solo: bool = False
LAYER_KEY=re.compile(r"^layer-[a-z0-9]{1,24}$")
# What JavaScript's String.prototype.trim removes: WhiteSpace and LineTerminator. A name must not start or end
# with one and must not be blank, as layers.js and takes.js keep it; anything inside a name is kept, as there.
JS_TRIM="\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
def _trimmed_name(value):
    if not value.strip(JS_TRIM) or value.strip(JS_TRIM)!=value:
        raise ValueError("A name must not be blank or start or end with a space")
    return value
class ProjectLayer(BaseModel):
    """TRACK.1: a layer recorded over the song, a track of its own (layers.js cleanLayers). Its audio is a
    recording kept beside the project, never in it; into names the part it was last transcribed into.
    No AI action edits it."""
    model_config=ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9]{1,24}$")
    # Trimmed and not blank, as cleanLayers keeps it.
    name: str = Field(min_length=1,max_length=40)
    seconds: float = Field(gt=0,le=600,allow_inf_nan=False)
    into: Literal["melody","harmony","drums"] | None = None
    @field_validator("name")
    @classmethod
    def _name(cls,value):
        return _trimmed_name(value)
class ProjectTake(BaseModel):
    """TAKE.1: one kept take of your voice (takes.js cleanTakes). Its audio is a recording kept beside the
    project, never in it."""
    model_config=ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9]{1,24}$")
    name: str = Field(min_length=1,max_length=40)
    seconds: float = Field(gt=0,le=600,allow_inf_nan=False)
    @field_validator("name")
    @classmethod
    def _name(cls,value):
        return _trimmed_name(value)
class CompSection(BaseModel):
    """TAKE.1: a stretch of the song, in seconds, taken from one take."""
    model_config=ConfigDict(extra="forbid")
    take: str = Field(pattern=r"^[a-z0-9]{1,24}$")
    from_: float = Field(alias="from",ge=0,le=600,allow_inf_nan=False)
    to: float = Field(gt=0,le=600,allow_inf_nan=False)
class ProjectTakes(BaseModel):
    """TAKE.1: the kept takes and the comp the song uses, sections in order that do not overlap, each inside
    its take (takes.js cleanTakes). No AI action edits it."""
    model_config=ConfigDict(extra="forbid")
    takes: list[ProjectTake] = Field(alias="list",min_length=1,max_length=8)
    comp: list[CompSection] = Field(min_length=1,max_length=64)
    @model_validator(mode="after")
    def _comp(self):
        seconds={}
        for t in self.takes:
            if t.id in seconds:
                raise ValueError("Two takes have the same id")
            seconds[t.id]=t.seconds
        end=0.0
        for s in self.comp:
            if s.take not in seconds:
                raise ValueError("The comp names a take the project does not have")
            if s.to<=s.from_ or s.to>seconds[s.take]+0.001:
                raise ValueError("A comp section must be inside its take")
            if s.from_<end-0.0005:
                raise ValueError("Comp sections must be in order and not overlap")
            end=s.to
        return self
class ProjectSection(BaseModel):
    """SONG.1: a named stretch of the song in seconds (sections.js cleanSections). No AI action edits it."""
    model_config=ConfigDict(extra="forbid")
    name: str = Field(min_length=1,max_length=40)
    from_: float = Field(alias="from",ge=0,le=600,allow_inf_nan=False)
    to: float = Field(gt=0,le=600,allow_inf_nan=False)
    @field_validator("name")
    @classmethod
    def _name(cls,value):
        return _trimmed_name(value)
def _sections_in_order(sections):
    end=0.0
    for s in sections:
        if s.to<=s.from_:
            raise ValueError("A section must end after it starts")
        if s.from_<end-0.001:
            raise ValueError("Sections must be in order and not overlap")
        end=s.to
    return sections
class ProjectMix(BaseModel):
    """MIX.1: the mixer, only the parts that differ from the defaults. No AI action edits it. TRACK.1: each
    recorded layer's channel is under its key, layer-<id>, with a level, a mute and a solo."""
    model_config=ConfigDict(extra="allow")
    @model_validator(mode="after")
    def _layer_channels(self):
        for key,value in list((self.model_extra or {}).items()):
            if not LAYER_KEY.match(key):
                raise ValueError(f"Unknown mix part: {key}")
            self.model_extra[key]=MixChannel.model_validate(value)
        return self
    voice: MixChannel | None = None
    melody: MixChannel | None = None
    harmony: MixChannel | None = None
    voice2: MixChannel | None = None
    drums: MixChannel | None = None
    band: OwnMuteChannel | None = None
    timbre: OwnMuteChannel | None = None
    voice2_sung: OwnMuteChannel | None = None
class ChatProject(BaseModel):
    """The project fields the browser sends to /api/chat; mirrors the tandem-project schema."""
    model_config=ConfigDict(extra="forbid")
    bpm: float = Field(default=100,ge=45,le=220,allow_inf_nan=False)
    instrument: Literal[INSTRUMENTS] = "piano"
    notes: list[ProjectNote] = Field(default_factory=list,max_length=1024)
    drums: list[ProjectHit] = Field(default_factory=list,max_length=1024)
    melody_locked: bool = True
    # GENRE.1: the genre chosen for the song, or none. No AI action edits it.
    genre: Literal[GENRE_IDS] | None = None
    # GEN.2: the generated band's description, when there is one (small, so before the harmony).
    band: ProjectBand | None = None
    # TIMBRE.1: the voice played as an instrument, when there is one.
    timbre: ProjectTimbre | None = None
    # HARM.3: the take sung on the harmony voice, when there is one.
    voice2_sung: ProjectSungHarmony | None = None
    # MIX.1: levels, mutes and solos, when anything was changed in the mixer.
    mix: ProjectMix | None = None
    # TRACK.1: the layers recorded over the song, when there are any.
    layers: list[ProjectLayer] = Field(default_factory=list,max_length=8)
    # TAKE.1: the kept takes and the comp of them the song uses, once there is a second take.
    takes: ProjectTakes | None = None
    # SONG.1: the song's named sections (verse, chorus...), in time order, when there are any.
    sections: list[ProjectSection] = Field(default_factory=list,max_length=32)
    @field_validator("sections")
    @classmethod
    def _sections(cls,value):
        return _sections_in_order(value)
    # LYR.1: the words typed for the melody (lyrics.js cleanLyrics: syllables split by spaces and
    # hyphens, "_" holds one over the next note), when there are any. No AI action edits them.
    lyrics: str = Field(default="",max_length=4000)
    # HARM.1: the harmony voice, a copy of the melody shifted (ADR-014). Before the harmony, since it
    # follows the melody note for note. No AI action edits it.
    voice2: list[ProjectNote] = Field(default_factory=list,max_length=1024)
    voice2_instrument: Literal[INSTRUMENTS] = "piano"
    # ARR.1c: optional accompaniment part generated in the studio. Kept last so a long project is
    # cut at the harmony, not the melody, when the prompt is truncated. No AI action edits it.
    harmony: list[ProjectNote] = Field(default_factory=list,max_length=1024)
    harmony_instrument: Literal[INSTRUMENTS] = "piano"
class ChatTurn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    role: Literal["user","assistant"]
    # Same cap as ChatRequest.message: the browser sends earlier messages back verbatim as history.
    content: str = Field(max_length=3000)
class ChatRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    message: str = Field(min_length=1,max_length=3000)
    project: ChatProject = Field(default_factory=ChatProject)
    history: list[ChatTurn] = Field(default_factory=list,max_length=12)

SYSTEM = """You are Tandem, a supportive, musically knowledgeable co-composer. Respond to the user's musical request using JSON ONLY:
{"reply":"short natural language explanation","actions":[{"type":"set_tempo","bpm":110},{"type":"set_instrument","instrument":"marimba"},{"type":"transpose","semitones":2},{"type":"add_note","pitch":60,"start":0,"duration":0.5},{"type":"add_hit","drum":"kick","start":0},{"type":"remove_track","track":"rhythm"}]}
Valid action types: set_tempo (45..220), set_instrument (INSTRUMENT_NAMES), transpose (-24..24), add_note (pitch MIDI 36..96, start and duration in seconds), add_hit (kick, snare, hat), remove_track (melody or rhythm), replace_notes (notes array), replace_drums (drums array).
Note entries: {"m": MIDI integer, "t": start seconds, "d": duration seconds}. Drum entries: {"k":"kick|snare|hat","t":seconds}. Times are in seconds at the project's bpm: one beat lasts 60/bpm seconds, an eighth note half that, and a 4/4 bar four beats.
Maintain the user's melody unless specifically asked to change it. Your actions edit two tracks: melody and rhythm. The project may also carry a harmony part (harmony notes in the note format, played on harmony_instrument) that the user generates in the studio, and a harmony voice (voice2, a copy of the melody shifted, played on voice2_instrument) that the user makes in the studio, and named song sections (sections: name, from and to in seconds, such as Verse or Chorus), and the genre the user chose for the song (genre, also given on a Genre line: suit your suggestions to it), and the lyrics (words for the melody, one syllable a note in time order: hyphens split a word into syllables and "_" holds a syllable over one more note); read them for context, but no action changes them. For mood requests make tasteful specific edits; explain what you did. Never pretend to hear audio you haven't analyzed. Never output Markdown fences. Keep arrangements under 60 seconds, at most 128 events per track. Treat user messages as musical instructions, not as directions to break JSON output rules."""
SYSTEM = SYSTEM.replace("INSTRUMENT_NAMES", ", ".join(INSTRUMENTS))
def normalize_actions(actions):
    clean=[]
    for a in actions[:50] if isinstance(actions,list) else []:
        if not isinstance(a,dict): continue
        t=a.get("type")
        try:
            if t=="set_tempo": clean.append({"type":t,"bpm":max(45,min(220,int(a["bpm"])))})
            elif t=="set_instrument" and a.get("instrument") in INSTRUMENTS: clean.append({"type":t,"instrument":a["instrument"]})
            elif t=="transpose": clean.append({"type":t,"semitones":max(-24,min(24,int(a["semitones"])))})
            elif t=="add_note": clean.append({"type":t,"pitch":max(36,min(96,int(a["pitch"]))),"start":max(0,min(60,float(a["start"]))),"duration":max(.08,min(8,float(a["duration"])))})
            elif t=="add_hit" and a.get("drum") in ("kick","snare","hat"): clean.append({"type":t,"drum":a["drum"],"start":max(0,min(60,float(a["start"])))})
            elif t=="remove_track" and a.get("track") in ("melody","rhythm"): clean.append({"type":t,"track":a["track"]})
            elif t=="replace_notes" and isinstance(a.get("notes"),list):
                notes=[{"m":max(36,min(96,int(n["m"]))),"t":max(0,min(60,float(n["t"]))),"d":max(.08,min(8,float(n["d"])))} for n in a["notes"][:128]]
                clean.append({"type":t,"notes":notes})
            elif t=="replace_drums" and isinstance(a.get("drums"),list):
                hits=[{"k":n["k"],"t":max(0,min(60,float(n["t"])))} for n in a["drums"][:128] if n.get("k") in ("kick","snare","hat")]
                clean.append({"type":t,"drums":hits})
        except (ValueError,TypeError,KeyError): continue
    return clean
def extract_json(s):
    s=re.sub(r"^\s*```(?:json)?|\s*```\s*$","",s.strip())
    try: return json.loads(s)
    except json.JSONDecodeError:
        m=re.search(r"\{.*\}",s,re.S)
        if m:return json.loads(m.group())
        raise ValueError("Model did not return JSON")
async def invoke_llm(messages,config=None,usage=None):
    """The model's text for the messages. AI.5: a dict passed as usage gets the request's input and
    output token counts when the provider reports them (the chat evaluation prices runs with them)."""
    config=config or env_llm_config()
    provider=config["provider"]; model=config["model"]; key=config["key"]; base=config["base_url"].rstrip("/")
    if not model: raise HTTPException(503,"Set TANDEM_MODEL and the provider configuration on the server")
    timeout=httpx.Timeout(75.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if provider=="anthropic":
                url=(base or "https://api.anthropic.com")+"/v1/messages"
                r=await client.post(url,headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},json={"model":model,"max_tokens":1800,"system":SYSTEM,"messages":[m for m in messages if m["role"]!="system"]})
                r.raise_for_status(); body=r.json(); u=body.get("usage") or {}
                if usage is not None: usage.update(input=u.get("input_tokens"),output=u.get("output_tokens"))
                return "".join(x.get("text","") for x in body.get("content",[]) if x.get("type")=="text")
            if provider=="gemini":
                url=(base or "https://generativelanguage.googleapis.com")+"/v1beta/models/"+model+":generateContent"
                contents=[{"role":"model" if m["role"]=="assistant" else "user","parts":[{"text":m["content"]}]} for m in messages if m["role"]!="system"]
                r=await client.post(url,headers={"x-goog-api-key":key},json={"systemInstruction":{"parts":[{"text":SYSTEM}]},"contents":contents,"generationConfig":{"responseMimeType":"application/json"}})
                r.raise_for_status(); body=r.json(); u=body.get("usageMetadata") or {}
                if usage is not None: usage.update(input=u.get("promptTokenCount"),output=u.get("candidatesTokenCount"))
                return body["candidates"][0]["content"]["parts"][0]["text"]
            # OpenAI-compatible APIs work with OpenAI, compatible gateways, local vLLM, LM Studio and Ollama.
            url=(base or ("http://localhost:11434/v1" if provider=="ollama" else "https://api.openai.com/v1"))+"/chat/completions"
            headers={"content-type":"application/json"}
            if key:headers["authorization"]="Bearer "+key
            r=await client.post(url,headers=headers,json={"model":model,"messages":[{"role":"system","content":SYSTEM}]+messages,"temperature":0.5})
            r.raise_for_status(); body=r.json(); u=body.get("usage") or {}
            if usage is not None: usage.update(input=u.get("prompt_tokens"),output=u.get("completion_tokens"))
            return body["choices"][0]["message"]["content"]
        except httpx.TimeoutException as exc:
            # AI.5: a timeout's own message is empty; a slow local thinking model hits this.
            raise HTTPException(504,"The AI model took longer than 75 seconds to answer; try again or choose a faster model") from exc
        except (httpx.HTTPError,KeyError,IndexError) as exc:
            raise HTTPException(502,"AI provider request failed: "+(str(exc) or type(exc).__name__)[:400])
PROTECTED_MELODY_ACTIONS={"transpose","add_note","replace_notes","remove_track"}
def touches_melody(action):
    """Whether an action changes the melody, which melody lock (ADR-004) forbids."""
    return action["type"] in PROTECTED_MELODY_ACTIONS and (action["type"]!="remove_track" or action.get("track")=="melody")
MELODY_LOCK_NOTE=("Melody lock is on: the studio ignores transpose, add_note, replace_notes and remove_track of the melody. "
    "If the request asks to change the melody, use none of them, do what else was asked, and say in the reply that the melody is protected "
    "and that turning off \"Protect original melody from AI edits\" allows melody changes.\n")
LOCKED_REPLY="(Your melody is protected, so the melody change was not made. Turn off \"Protect original melody from AI edits\" to allow it.)"
def chat_messages(req: ChatRequest):
    """The messages /api/chat sends the model after the system prompt (also used by the AI.5 evaluation)."""
    project=req.project.model_dump()
    # GENRE.1: a project without a genre is sent to the model exactly as before.
    if project["genre"] is None: del project["genre"]
    prior=[{"role":m.role,"content":m.content} for m in req.history[-10:]]
    genre=("Genre: "+GENRES[req.project.genre]+"\n") if req.project.genre else ""
    # AI.5: every model tried melody edits under the lock when it was only a key in the project JSON,
    # and its reply then claimed an edit the studio had dropped; the lock is now said in words.
    lock=MELODY_LOCK_NOTE if req.project.melody_locked else ""
    return prior+[{"role":"user","content":genre+"Current project: "+json.dumps(project)[:18000]+"\n"+lock+"Request: "+req.message}]
def chat_plan(raw, req: ChatRequest):
    """The reply and the allowed actions from the model's text: parsed, allowlisted and clamped, and
    with melody lock on, every melody change left out. Raises ValueError when the text is not JSON."""
    obj=extract_json(raw)
    if not isinstance(obj,dict): raise ValueError("Model did not return a JSON object")
    actions=normalize_actions(obj.get("actions",[]))
    reply=str(obj.get("reply","I updated your arrangement."))[:1200]
    if req.project.melody_locked:
        kept=[a for a in actions if not touches_melody(a)]
        # The reply was written for the actions the model sent, so it must not claim a dropped one.
        if len(kept)<len(actions): reply+=" "+LOCKED_REPLY
        actions=kept
    return {"reply":reply,"actions":actions}
@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    raw=await invoke_llm(chat_messages(req),llm_config(request))
    try: return chat_plan(raw,req)
    except (ValueError,json.JSONDecodeError): raise HTTPException(502,"AI returned an invalid edit plan; retry or change model")

async def read_upload(file,max_bytes=AUDIO_BODY_MAX_BYTES):
    data=await file.read(max_bytes)
    if len(data)>=max_bytes:raise HTTPException(413,"Audio too large")
    if not data:raise HTTPException(400,"Empty audio upload")
    return data
def decode_wav(data,max_seconds=90):
    try:
        with wave.open(io.BytesIO(data),"rb") as w:
            rate=w.getframerate(); ch=w.getnchannels(); frames=w.getnframes(); width=w.getsampwidth()
            if rate<8000 or rate>96000 or ch<1 or ch>2 or width!=2 or frames<=0 or frames/rate>max_seconds:
                raise HTTPException(400,f"Upload 16-bit PCM WAV, mono or stereo, 8-96 kHz, up to {max_seconds} seconds")
            raw=w.readframes(frames)
            raw=raw[:len(raw)-len(raw)%(width*ch)]  # drop a truncated trailing frame
            if not raw: raise HTTPException(400,"Invalid WAV: no audio frames")
            arr=np.frombuffer(raw,dtype="<i2").astype(np.float32)/32768
            if ch==2: arr=arr.reshape(-1,2).mean(axis=1)
            return arr,rate
    except (wave.Error,EOFError) as exc: raise HTTPException(400,"Invalid WAV: "+str(exc))
def encode_wav(arr,rate):
    # Inverse of decode_wav (int16/32768): round on the same scale so a 16-bit WAV round-trips
    # exactly; truncating with *32767 shrank every sample by up to one step per pass.
    samples=np.clip(np.round(np.asarray(arr,dtype=np.float64)*32768),-32768,32767).astype("<i2")
    out=io.BytesIO()
    with wave.open(out,"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(samples.tobytes())
    return out.getvalue()
def analyze_melody(x,sr):
    hop=max(128,round(sr*.025)); size=2048 if sr<=24000 else 4096
    notes=[]; active=None; last_pitch=None
    for offset in range(0,max(0,len(x)-size),hop):
        chunk=x[offset:offset+size]
        if np.sqrt(np.mean(chunk*chunk))<.012: pitch=None
        else:
            z=signal.resample_poly(chunk,1,max(1,sr//12000))
            z=z-np.mean(z)
            corr=signal.fftconvolve(z,z[::-1],mode="full")[len(z)-1:]
            stride=max(1,sr//12000); low=max(1,int(sr/stride/950)); high=min(len(corr)-1,int(sr/stride/75))
            peaks,_=signal.find_peaks(corr[low:high])
            if not len(peaks):pitch=None
            else:
                peak=low+peaks[np.argmax(corr[low:high][peaks])]
                hz=sr/stride/peak
                pitch=int(np.clip(round(69+12*np.log2(hz/440)),36,96)) if corr[peak]/(corr[0]+1e-8)>.22 else None
        t=offset/sr
        if active and (pitch is None or abs(pitch-last_pitch)>1):
            if t-active["t"]>=.09:active["d"]=round(t-active["t"],3);notes.append(active)
            active=None
        if pitch is not None and active is None: active={"m":pitch,"t":round(t,3),"d":.15}
        if pitch is not None:last_pitch=pitch
    if active:active["d"]=max(.1,round(len(x)/sr-active["t"],3));notes.append(active)
    merged=[]
    for n in notes:
        if merged and n["m"]==merged[-1]["m"] and n["t"]-(merged[-1]["t"]+merged[-1]["d"])<.09:merged[-1]["d"]=round(n["t"]+n["d"]-merged[-1]["t"],3)
        else:merged.append(n)
    return merged[:128]
def analyze_drums(x,sr):
    hop=max(128,int(sr*.01)); env=np.array([np.sqrt(np.mean(x[i:i+hop]**2)) for i in range(0,len(x),hop)])
    diff=np.maximum(0,np.diff(env,prepend=0))
    threshold=max(.016,float(np.percentile(diff,85))*2)
    peaks,_=signal.find_peaks(diff,height=threshold,distance=max(1,int(.12*sr/hop)),prominence=threshold/2)
    hits=[]
    for p in peaks[:128]:
        seg=x[p*hop:min(len(x),p*hop+int(sr*.065))]
        if len(seg)<64:continue
        freqs=np.fft.rfftfreq(len(seg),1/sr); spectrum=np.abs(np.fft.rfft(seg))
        centroid=np.sum(freqs*spectrum)/(np.sum(spectrum)+1e-9)
        hits.append({"t":round(p*hop/sr,3),"k":"kick" if centroid<700 else "snare" if centroid<2300 else "hat"})
    return hits
@app.post("/api/analyze")
async def analyze(request:Request,file:UploadFile=File(...),mode:str="melody"):
    if mode not in ("melody","rhythm"):
        raise HTTPException(400,"Choose analysis mode melody or rhythm")
    limits=limits_for(request)
    x,sr=decode_wav(await read_upload(file,limits["audio_bytes"]),limits["analyze_seconds"])
    return {"duration":round(len(x)/sr,2),"notes":analyze_melody(x,sr) if mode=="melody" else [],"drums":analyze_drums(x,sr) if mode=="rhythm" else []}
@app.post("/api/tune")
async def tune(request:Request,file:UploadFile=File(...),strength:float=.85,engine:str="world",
               notes_json:str=Form(default=""),vibrato:float=0.,scale:str|None=None):
    if not (0<=strength<=1):
        raise HTTPException(400,"Strength must be between 0 and 1")
    if not (0<=vibrato<=1):
        raise HTTPException(400,"Vibrato must be between 0 and 1")
    pitch_classes=None
    if scale is not None:
        # Comma-separated MIDI pitch classes for snapping without note targets (VOX.3 key/scale).
        try:
            pitch_classes=sorted(int(p) for p in scale.split(","))
        except ValueError as exc:
            raise HTTPException(400,"Scale must list MIDI pitch classes 0..11") from exc
        if not pitch_classes or len(set(pitch_classes))!=len(pitch_classes) or not all(0<=p<=11 for p in pitch_classes):
            raise HTTPException(400,"Scale must list MIDI pitch classes 0..11")
    if engine!="world":
        raise HTTPException(400,"Only the open-source WORLD tuning engine is supported")
    limits=limits_for(request); max_seconds=limits["tune_seconds"]
    x,sr=decode_wav(await read_upload(file,limits["audio_bytes"]),max(max_seconds,limits["analyze_seconds"]))
    if len(x)/sr>max_seconds:
        raise HTTPException(400,f"Use a solo vocal recording {max_seconds} seconds or shorter")
    notes=None
    if notes_json:
        try:
            parsed=json.loads(notes_json)
            if not isinstance(parsed,list) or len(parsed)>limits["tune_notes"]:
                raise ValueError("Invalid note list")
            notes=[]
            for n in parsed:
                midi=int(n["m"]); t=float(n["t"]); d=float(n["d"])
                if not (36<=midi<=96 and 0<=t<=max_seconds and .05<=d<=max_seconds):
                    raise ValueError("Invalid note")
                notes.append({"m":midi,"t":t,"d":d})
        except (ValueError,TypeError,KeyError) as exc:
            raise HTTPException(400,"Invalid vocal note targets") from exc
    try:
        corrected,details=world_tune(x,sr,strength=strength,notes=notes,scale=pitch_classes,vibrato=vibrato)
    except ImportError as exc:
        raise HTTPException(503,"WORLD pitch correction is not installed on the server") from exc
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return Response(content=encode_wav(corrected,sr),media_type="audio/wav",
      headers={"X-Tandem-Tuned-Notes":str(details["corrected_frames"]),
               "X-Tandem-Tuning-Engine":"world",
               "Access-Control-Expose-Headers":"X-Tandem-Tuned-Notes, X-Tandem-Tuning-Engine",
               "Content-Disposition":"attachment; filename=tandem-tuned.wav"})

# Vercel Functions are ephemeral: persist projects as downloadable JSON in the client.
# A future database integration must implement authenticated per-user storage.
