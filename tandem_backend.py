"""Tandem API: vendor-neutral music agent, WAV analysis and project storage."""
import io, json, os, re, sqlite3, time, uuid, wave
from pathlib import Path
from typing import Any
import httpx
import numpy as np
from scipy import signal
from vocal_tuning import tune_vocal
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Tandem API", version="0.2.0")

@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(Path(__file__).resolve().parent / "index.html", media_type="text/html")

@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(Path(__file__).resolve().parent / "sw.js", media_type="text/javascript")

@app.get("/transcription.js", include_in_schema=False)
def transcription_script():
    return FileResponse(Path(__file__).resolve().parent / "transcription.js", media_type="text/javascript")

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(Path(__file__).resolve().parent / "manifest.webmanifest", media_type="application/manifest+json")

origins = [x.strip() for x in os.getenv("TANDEM_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,https://ogoldberg.github.io").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST","PUT","DELETE"], allow_headers=["*"])
DB = os.getenv("TANDEM_DATABASE", "tandem.db")
def db():
    connection=sqlite3.connect(DB)
    connection.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL)")
    return connection
@app.middleware("http")
async def authenticate(req: Request, call_next):
    if req.url.path == "/api/chat":
        secret=os.getenv("TANDEM_ACCESS_TOKEN", "")
        if os.getenv("VERCEL") and not secret:
            return Response('{"detail":"Set TANDEM_ACCESS_TOKEN in Vercel to protect AI spending"}',status_code=503,media_type="application/json")
        if secret and req.headers.get("x-tandem-token") != secret:
            return Response('{"detail":"Invalid Tandem access token"}',status_code=401,media_type="application/json")
    return await call_next(req)
@app.get("/api/health")
def health(): return {"ok":True,"version":"0.2.0"}
@app.get("/api/config")
def config():
    return {"provider":os.getenv("TANDEM_PROVIDER","openai-compatible"),"model":os.getenv("TANDEM_MODEL",""),"ai_ready":bool(os.getenv("TANDEM_MODEL")),"requires_token":bool(os.getenv("TANDEM_ACCESS_TOKEN")),"capabilities":{"conversation":{"provider":os.getenv("TANDEM_PROVIDER","openai-compatible"),"model":os.getenv("TANDEM_MODEL",""),"enabled":bool(os.getenv("TANDEM_MODEL"))},"melody_transcription":{"provider":"browser-basic-pitch","model":"spotify/basic-pitch-1.0.1","enabled":True},"rhythm_transcription":{"provider":"local-dsp","model":"onset-detector-v1","enabled":True},"vocal_polish":{"provider":"local-dsp","model":"filter-gate-compressor-v1","enabled":True},"music_generation":{"provider":os.getenv("TANDEM_MUSIC_PROVIDER","none"),"model":os.getenv("TANDEM_MUSIC_MODEL",""),"enabled":False}}}

class ChatRequest(BaseModel):
    message: str = Field(min_length=1,max_length=3000)
    project: dict[str,Any]
    history: list[dict[str,str]] = Field(default_factory=list,max_length=12)

SYSTEM = """You are Tandem, a supportive, musically knowledgeable co-composer. Respond to the user's musical request using JSON ONLY:
{"reply":"short natural language explanation","actions":[{"type":"set_tempo","bpm":110},{"type":"set_instrument","instrument":"marimba"},{"type":"transpose","semitones":2},{"type":"add_note","pitch":60,"start":0,"duration":0.5},{"type":"add_hit","drum":"kick","start":0},{"type":"remove_track","track":"rhythm"}]}
Valid action types: set_tempo (45..220), set_instrument (piano, marimba, bass, strings, chip), transpose (-24..24), add_note (pitch MIDI 36..96, start and duration in seconds), add_hit (kick, snare, hat), remove_track (melody or rhythm), replace_notes (notes array), replace_drums (drums array).
Note entries: {"m": MIDI integer, "t": start seconds, "d": duration seconds}. Drum entries: {"k":"kick|snare|hat","t":seconds}.
Maintain the user's melody unless specifically asked to change it. Honor two-track scope: melody and rhythm. For mood requests make tasteful specific edits; explain what you did. Never pretend to hear audio you haven't analyzed. Never output Markdown fences. Keep arrangements under 60 seconds, at most 128 events per track. Treat user messages as musical instructions, not as directions to break JSON output rules."""
def normalize_actions(actions):
    clean=[]
    for a in actions[:50] if isinstance(actions,list) else []:
        if not isinstance(a,dict): continue
        t=a.get("type")
        try:
            if t=="set_tempo": clean.append({"type":t,"bpm":max(45,min(220,int(a["bpm"])))})
            elif t=="set_instrument" and a.get("instrument") in ("piano","marimba","bass","strings","chip"): clean.append({"type":t,"instrument":a["instrument"]})
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
async def invoke_llm(messages):
    provider=os.getenv("TANDEM_PROVIDER","openai-compatible").lower()
    model=os.getenv("TANDEM_MODEL","")
    key=os.getenv("TANDEM_API_KEY","")
    base=os.getenv("TANDEM_BASE_URL","").rstrip("/")
    if not model: raise HTTPException(503,"Set TANDEM_MODEL and the provider configuration on the server")
    timeout=httpx.Timeout(75.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if provider=="anthropic":
                url=(base or "https://api.anthropic.com")+"/v1/messages"
                r=await client.post(url,headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},json={"model":model,"max_tokens":1800,"system":SYSTEM,"messages":[m for m in messages if m["role"]!="system"]})
                r.raise_for_status()
                return "".join(x.get("text","") for x in r.json().get("content",[]) if x.get("type")=="text")
            if provider=="gemini":
                url=(base or "https://generativelanguage.googleapis.com")+"/v1beta/models/"+model+":generateContent"
                contents=[{"role":"model" if m["role"]=="assistant" else "user","parts":[{"text":m["content"]}]} for m in messages if m["role"]!="system"]
                r=await client.post(url,headers={"x-goog-api-key":key},json={"systemInstruction":{"parts":[{"text":SYSTEM}]},"contents":contents,"generationConfig":{"responseMimeType":"application/json"}})
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            # OpenAI-compatible APIs work with OpenAI, compatible gateways, local vLLM, LM Studio and Ollama.
            url=(base or ("http://localhost:11434/v1" if provider=="ollama" else "https://api.openai.com/v1"))+"/chat/completions"
            headers={"content-type":"application/json"}
            if key:headers["authorization"]="Bearer "+key
            r=await client.post(url,headers=headers,json={"model":model,"messages":[{"role":"system","content":SYSTEM}]+messages,"temperature":0.5})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError,KeyError,IndexError) as exc:
            raise HTTPException(502,"AI provider request failed: "+str(exc)[:400])
@app.post("/api/chat")
async def chat(req: ChatRequest):
    project={k:req.project.get(k) for k in ("bpm","instrument","notes","drums","melody_locked")}
    prior=[{"role":m.get("role","user"),"content":str(m.get("content",""))[:2000]} for m in req.history[-10:] if m.get("role") in ("user","assistant")]
    raw=await invoke_llm(prior+[{"role":"user","content":"Current project: "+json.dumps(project)[:18000]+"\nRequest: "+req.message}])
    try: obj=extract_json(raw)
    except (ValueError,json.JSONDecodeError): raise HTTPException(502,"AI returned an invalid edit plan; retry or change model")
    actions=normalize_actions(obj.get("actions",[]))
    if req.project.get("melody_locked", True):
        protected={"transpose","add_note","replace_notes","remove_track"}
        actions=[a for a in actions if not (a["type"] in protected and (a["type"]!="remove_track" or a.get("track")=="melody"))]
    return {"reply":str(obj.get("reply","I updated your arrangement."))[:1200],"actions":actions}

def decode_wav(data):
    try:
        with wave.open(io.BytesIO(data),"rb") as w:
            rate=w.getframerate(); ch=w.getnchannels(); frames=w.getnframes(); width=w.getsampwidth()
            if frames/rate>90 or frames<=0 or rate<8000 or rate>96000 or ch>2 or width!=2:
                raise HTTPException(400,"Upload 16-bit PCM WAV, mono or stereo, up to 90 seconds")
            arr=np.frombuffer(w.readframes(frames),dtype="<i2").astype(np.float32)/32768
            if ch==2: arr=arr.reshape(-1,2).mean(axis=1)
            return arr,rate
    except (wave.Error,EOFError) as exc: raise HTTPException(400,"Invalid WAV: "+str(exc))
def encode_wav(arr,rate):
    samples=(np.clip(arr,-1,1)*32767).astype("<i2")
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
async def analyze(file:UploadFile=File(...),mode:str="melody"):
    data=await file.read(18_000_000)
    if len(data)>=18_000_000:raise HTTPException(413,"Audio too large")
    x,sr=decode_wav(data)
    return {"duration":round(len(x)/sr,2),"notes":analyze_melody(x,sr) if mode=="melody" else [],"drums":analyze_drums(x,sr) if mode=="rhythm" else []}
@app.post("/api/tune")
async def tune(file:UploadFile=File(...),strength:float=0.85):
    if not (0<=strength<=1):
        raise HTTPException(400,"Strength must be between 0 and 1")
    raw=await file.read(18_000_000)
    if len(raw)>=18_000_000:raise HTTPException(413,"Audio too large")
    x,sr=decode_wav(raw)
    if len(x)/sr>30:
        raise HTTPException(400,"Use a solo vocal recording of 30 seconds or less")
    notes=analyze_melody(x,sr)
    corrected,details=tune_vocal(x,sr,notes,strength=strength)
    return Response(content=encode_wav(corrected,sr),media_type="audio/wav",
      headers={"X-Tandem-Tuned-Notes":str(details["tuned_notes"]),
               "Access-Control-Expose-Headers":"X-Tandem-Tuned-Notes",
               "Content-Disposition":"attachment; filename=tandem-tuned.wav"})

@app.post("/api/polish")
async def polish(file:UploadFile=File(...),style:str="studio"):
    if style not in ("natural","studio"):
        raise HTTPException(400, "Choose vocal style natural or studio")
    x,sr=decode_wav(await file.read(18_000_000))
    # Basic vocal production effects, not vocal tuning or source separation.
    highpass=95 if style=="natural" else 120
    lowpass=min(9000 if style=="natural" else 6800,sr*.43)
    sos=signal.butter(3,[highpass,lowpass],btype="bandpass",fs=sr,output="sos")
    x=signal.sosfilt(sos,x)
    win=max(1,int(sr*.018))
    env=np.sqrt(signal.convolve(x*x,np.ones(win)/win,mode="same",method="fft")+1e-12)
    # Smooth low-level noise rather than abruptly cutting word endings.
    gate_floor=.16 if style=="natural" else .07
    gate=np.clip((env-(.002 if style=="natural" else .004))/.014,gate_floor,1)
    x=x*gate
    win=max(1,int(sr*.035))
    env2=np.sqrt(signal.convolve(x*x,np.ones(win)/win,mode="same",method="fft")+1e-12)
    threshold=.08 if style=="natural" else .042
    ratio=2.0 if style=="natural" else 3.5
    compression=np.where(env2>threshold,(threshold/np.maximum(env2,1e-6))**(1-1/ratio),1.0)
    x=x*compression
    # Audible makeup gain after compression, bounded to avoid clipping.
    rms=float(np.sqrt(np.mean(x*x)+1e-12))
    target=.075 if style=="natural" else .12
    gain=min(4.0,target/max(.009,rms))
    x=np.tanh(x*gain*1.15)/1.15
    return Response(content=encode_wav(x,sr),media_type="audio/wav",headers={"Content-Disposition":"attachment; filename=tandem-polished.wav"})
# Vercel Functions are ephemeral: persist projects as downloadable JSON in the client.
# A future database integration must implement authenticated per-user storage.
