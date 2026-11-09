import asyncio
import io
import json
import wave
import httpx
import numpy as np
import pytest
import tandem_backend as server

def run(coro):
    return asyncio.run(coro)

@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setattr(server,"DB",str(tmp_path/"test.db"))
    monkeypatch.delenv("TANDEM_ACCESS_TOKEN",raising=False)
    async def call(method,path,**kwargs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url="http://test") as c:
            return await c.request(method,path,**kwargs)
    return call

def wav_bytes(samples,rate=16000):
    out=io.BytesIO()
    with wave.open(out,"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate)
        w.writeframes((np.clip(samples,-1,1)*32767).astype("<i2").tobytes())
    return out.getvalue()

def test_health_and_config(client,monkeypatch):
    monkeypatch.setenv("TANDEM_MODEL","example-model")
    assert run(client("GET","/api/health")).json()["ok"]
    assert run(client("GET","/api/config")).json()["ai_ready"]
    assert run(client("GET","/api/config")).json()["capabilities"]["melody_transcription"]["provider"] == "browser-basic-pitch"

def test_token_auth(client,monkeypatch):
    monkeypatch.setenv("TANDEM_ACCESS_TOKEN","secret")
    assert run(client("POST","/api/chat",json={"message":"hi","project":{}})).status_code==401
    assert run(client("GET","/api/health",headers={"x-tandem-token":"secret"})).status_code==200

def test_production_fails_closed_without_token(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TANDEM_ACCESS_TOKEN", raising=False)
    assert run(client("POST", "/api/chat", json={"message":"hi","project":{}})).status_code == 503
    monkeypatch.setenv("TANDEM_ACCESS_TOKEN", "secret")
    assert run(client("POST", "/api/chat", json={"message":"hi","project":{}})).status_code == 401

def test_free_audio_routes_not_blocked_by_missing_ai_token(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TANDEM_ACCESS_TOKEN", raising=False)
    rate=16000
    audio=wav_bytes(0.1*np.sin(2*np.pi*440*np.arange(rate)/rate))
    analysis=run(client("POST", "/api/analyze?mode=melody",
        files={"file":("melody.wav",audio,"audio/wav")}))
    polish=run(client("POST", "/api/polish",
        files={"file":("voice.wav",audio,"audio/wav")}))
    assert analysis.status_code==200
    assert polish.status_code==200
    assert polish.headers["content-type"]=="audio/wav"
    assert run(client("POST", "/api/chat",json={"message":"hi","project":{}})).status_code==503

def test_no_ephemeral_server_project_storage(client):
    # Project JSON is saved/loaded by the web client; ephemeral Vercel functions should not write SQLite.
    assert run(client("POST","/api/projects",json={"data":{}})).status_code==404

def test_action_validation():
    actions=[
        {"type":"set_tempo","bpm":500},
        {"type":"transpose","semitones":-99},
        {"type":"add_note","pitch":500,"start":-3,"duration":0},
        {"type":"add_hit","drum":"hat","start":0.25},
        {"type":"set_instrument","instrument":"malicious"},
        {"type":"execute_python","code":"print('unsafe')"}
    ]
    result=server.normalize_actions(actions)
    assert len(result)==4
    assert result[0]["bpm"]==220
    assert result[1]["semitones"]==-24
    assert result[2]=={"type":"add_note","pitch":96,"start":0,"duration":0.08}

def test_json_parsing():
    wrapped = "```json\n" + '{"reply":"Done","actions":[]}' + "\n```"
    assert server.extract_json(wrapped)["reply"] == "Done"

def test_chat_action_filter(client,monkeypatch):
    async def fake(messages):
        assert "Current project:" in messages[-1]["content"]
        return json.dumps({"reply":"Raised melody","actions":[
            {"type":"transpose","semitones":2},
            {"type":"execute_python","code":"not permitted"}]})
    monkeypatch.setattr(server,"invoke_llm",fake)
    r=run(client("POST","/api/chat",json={"message":"Raise melody","project":{"notes":[],"drums":[],"melody_locked":False}}))
    assert r.status_code==200
    assert r.json()["actions"]==[{"type":"transpose","semitones":2}]

def test_melody_lock_blocks_transcription_rewrites(client,monkeypatch):
    async def fake(messages):
        return json.dumps({"reply":"Added a rhythm", "actions":[
            {"type":"replace_notes","notes":[{"m":73,"t":0,"d":1}]},
            {"type":"add_hit","drum":"kick","start":0},
            {"type":"remove_track","track":"melody"}]})
    monkeypatch.setattr(server,"invoke_llm",fake)
    response=run(client("POST","/api/chat",json={"message":"Add drums","project":{
        "notes":[{"m":60,"t":0,"d":1}],"drums":[],"melody_locked":True
    }}))
    assert response.status_code==200
    assert response.json()["actions"]==[{"type":"add_hit","drum":"kick","start":0.0}]

def test_chat_bad_model_reply(client,monkeypatch):
    async def fake(messages): return "Not JSON"
    monkeypatch.setattr(server,"invoke_llm",fake)
    assert run(client("POST","/api/chat",json={"message":"Edit it","project":{}})).status_code==502

def test_chat_unconfigured(client,monkeypatch):
    monkeypatch.delenv("TANDEM_MODEL",raising=False)
    assert run(client("POST","/api/chat",json={"message":"Edit it","project":{}})).status_code==503

def test_analyze_sine_and_silence(client):
    rate=16000
    tone=wav_bytes(0.3*np.sin(2*np.pi*440*np.arange(rate)/rate))
    r=run(client("POST","/api/analyze?mode=melody",files={"file":("tone.wav",tone,"audio/wav")}))
    assert r.status_code==200
    assert any(abs(n["m"]-69)<=1 for n in r.json()["notes"])
    silence=wav_bytes(np.zeros(rate))
    r=run(client("POST","/api/analyze?mode=melody",files={"file":("silence.wav",silence,"audio/wav")}))
    assert r.status_code==200 and r.json()["notes"]==[]

def test_audio_validation(client):
    r=run(client("POST","/api/analyze",files={"file":("bad.wav",b"not audio","audio/wav")}))
    assert r.status_code==400

def test_vocal_polish(client):
    rate=16000
    tone=wav_bytes(.2*np.sin(2*np.pi*220*np.arange(rate)/rate))
    r=run(client("POST","/api/polish",files={"file":("voice.wav",tone,"audio/wav")}))
    assert r.status_code==200
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getframerate()==rate and w.getnframes()==rate

@pytest.mark.parametrize("provider,path,body",[
    ("openai-compatible","/chat/completions",'{"choices":[{"message":{"content":"OK"}}]}'),
    ("anthropic","/v1/messages",'{"content":[{"type":"text","text":"OK"}]}'),
    ("gemini","/v1beta/models/test-model:generateContent",'{"candidates":[{"content":{"parts":[{"text":"OK"}]}}]}')
])
def test_provider_adapters(monkeypatch,provider,path,body):
    monkeypatch.setenv("TANDEM_PROVIDER",provider)
    monkeypatch.setenv("TANDEM_MODEL","test-model")
    monkeypatch.setenv("TANDEM_API_KEY","test-key")
    monkeypatch.delenv("TANDEM_BASE_URL",raising=False)
    seen=[]
    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200,text=body)
    transport=httpx.MockTransport(handler)
    actual=httpx.AsyncClient
    monkeypatch.setattr(server.httpx,"AsyncClient",lambda **kwargs: actual(transport=transport,**kwargs))
    assert run(server.invoke_llm([{"role":"user","content":"hello"}]))=="OK"
    assert seen[0].endswith(path)


def test_client_model_module_is_served(client):
    response = run(client("GET", "/transcription.js"))
    assert response.status_code == 200
    assert "normalizeBasicPitchNotes" in response.text
