import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kendr.providers import get_secret

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import llm_text
from tasks.utils import log_task_update, resolve_output_path, write_binary_file, write_text_file


ELEVENLABS_API_BASE = "https://api.elevenlabs.io"


def _api_key() -> str:
    api_key = get_secret("ELEVENLABS_API_KEY", provider="elevenlabs", key="api_key")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is required for ElevenLabs agents.")
    return api_key


def _json_request(method: str, path: str, payload: dict | None = None, timeout: int = 60) -> dict:
    request = Request(
        ELEVENLABS_API_BASE + path,
        method=method,
        headers={
            "xi-api-key": _api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=json.dumps(payload or {}).encode("utf-8") if payload is not None else None,
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _binary_request(method: str, path: str, payload: dict, timeout: int = 120) -> bytes:
    request = Request(
        ELEVENLABS_API_BASE + path,
        method=method,
        headers={
            "xi-api-key": _api_key(),
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _multipart_request(path: str, fields: dict[str, str], file_field: str, file_path: str, timeout: int = 180) -> dict:
    boundary = f"----elevenlabs-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        if value in (None, ""):
            continue
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    file_name = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    body = b"".join(chunks)
    request = Request(
        ELEVENLABS_API_BASE + path,
        method="POST",
        headers={
            "xi-api-key": _api_key(),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        data=body,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"ElevenLabs speech-to-text request failed: {exc.code} {error_body}") from exc


def _write_outputs(agent_name: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"{agent_name}_{call_number}.txt", summary)
    write_text_file(f"{agent_name}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _voice_suffix(output_format: str) -> str:
    value = (output_format or "mp3_44100_128").lower()
    if value.startswith("mp3"):
        return ".mp3"
    if value.startswith("pcm"):
        return ".pcm"
    if value.startswith("ulaw"):
        return ".ulaw"
    if value.startswith("wav"):
        return ".wav"
    return ".bin"


def _fetch_voices(timeout: int = 60) -> list[dict]:
    for path in ("/v2/voices", "/v1/voices"):
        try:
            payload = _json_request("GET", path, None, timeout=timeout)
            voices = payload.get("voices", [])
            if isinstance(voices, list):
                return voices
        except Exception:
            continue
    raise RuntimeError("Unable to fetch ElevenLabs voices from /v2/voices or /v1/voices.")


def _resolve_voice_id(voices: list[dict], state: dict) -> str:
    explicit = (state.get("elevenlabs_voice_id") or state.get("voice_id") or "").strip()
    if explicit:
        return explicit
    requested_name = (state.get("elevenlabs_voice_name") or state.get("voice_name") or "").strip().lower()
    if requested_name:
        for voice in voices:
            if str(voice.get("name", "")).strip().lower() == requested_name:
                return str(voice.get("voice_id", "")).strip()
    if voices:
        return str(voices[0].get("voice_id", "")).strip()
    raise ValueError("No ElevenLabs voice could be resolved.")


def voice_catalog_agent(state):
    _, task_content, _ = begin_agent_session(state, "voice_catalog_agent")
    state["voice_catalog_calls"] = state.get("voice_catalog_calls", 0) + 1
    call_number = state["voice_catalog_calls"]
    query = (state.get("voice_search_query") or task_content or "").strip().lower()

    voices = _fetch_voices(timeout=int(state.get("elevenlabs_timeout", 60)))
    filtered = []
    for voice in voices:
        item = {
            "voice_id": voice.get("voice_id"),
            "name": voice.get("name"),
            "category": voice.get("category"),
            "description": voice.get("description", ""),
            "labels": voice.get("labels", {}),
            "preview_url": voice.get("preview_url", ""),
        }
        searchable = " ".join(
            [
                str(item.get("name", "")),
                str(item.get("category", "")),
                json.dumps(item.get("labels", {}), ensure_ascii=False),
                str(item.get("description", "")),
            ]
        ).lower()
        if not query or query in searchable:
            filtered.append(item)

    payload = {
        "query": query,
        "voices": filtered[:50],
        "voice_count": len(filtered),
    }
    summary = llm_text(
        f"""You are an ElevenLabs voice catalog agent.

Summarize these available voices for the requested use case.
If a query is present, recommend the most relevant voice choices and explain why.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:40000]}
"""
    )
    _write_outputs("voice_catalog_agent", call_number, summary, payload)
    state["elevenlabs_voices"] = filtered
    state["voice_catalog_summary"] = summary
    state["draft_response"] = summary
    log_task_update("Voice Catalog", f"Voice catalog pass #{call_number} completed.")
    return publish_agent_output(
        state,
        "voice_catalog_agent",
        summary,
        f"voice_catalog_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "speech_generation_agent"],
    )


def speech_generation_agent(state):
    _, task_content, _ = begin_agent_session(state, "speech_generation_agent")
    state["speech_generation_calls"] = state.get("speech_generation_calls", 0) + 1
    call_number = state["speech_generation_calls"]

    voices = state.get("elevenlabs_voices") or _fetch_voices(timeout=int(state.get("elevenlabs_timeout", 60)))
    voice_id = _resolve_voice_id(voices, state)
    text = (
        state.get("speech_text")
        or state.get("text_to_speak")
        or state.get("report_text")
        or state.get("draft_response")
        or task_content
        or state.get("current_objective")
        or state.get("user_query", "")
    ).strip()
    if not text:
        raise ValueError("speech_generation_agent requires speech_text, text_to_speak, draft_response, or task content.")

    output_format = state.get("elevenlabs_output_format", "mp3_44100_128")
    payload = {
        "text": text,
        "model_id": state.get("elevenlabs_model_id", "eleven_multilingual_v2"),
        "output_format": output_format,
    }
    voice_settings = {}
    for field in ("stability", "similarity_boost", "style", "speed", "use_speaker_boost"):
        key = f"elevenlabs_{field}"
        if state.get(key) is not None:
            voice_settings[field] = state[key]
    if voice_settings:
        payload["voice_settings"] = voice_settings

    audio_bytes = _binary_request(
        "POST",
        f"/v1/text-to-speech/{voice_id}",
        payload,
        timeout=int(state.get("elevenlabs_generation_timeout", 180)),
    )
    audio_filename = f"speech_generation_agent_{call_number}{_voice_suffix(output_format)}"
    write_binary_file(audio_filename, audio_bytes)
    audio_path = resolve_output_path(audio_filename)
    result_payload = {
        "voice_id": voice_id,
        "voice_name": next((voice.get("name") for voice in voices if voice.get("voice_id") == voice_id), ""),
        "text_length": len(text),
        "model_id": payload["model_id"],
        "output_format": output_format,
        "audio_file": audio_path,
    }
    summary = llm_text(
        f"""You are an ElevenLabs speech generation agent.

Summarize this audio generation result for the user.
State what was generated, which voice was used, and where the downloadable file was saved.

Payload:
{json.dumps(result_payload, indent=2, ensure_ascii=False)}
"""
    )
    _write_outputs("speech_generation_agent", call_number, summary, result_payload)
    state["speech_generation_result"] = result_payload
    state["speech_audio_file"] = audio_path
    state["draft_response"] = summary
    log_task_update("Speech Generation", f"Audio generated at {audio_path}")
    return publish_agent_output(
        state,
        "speech_generation_agent",
        summary,
        f"speech_generation_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )


def speech_transcription_agent(state):
    _, task_content, _ = begin_agent_session(state, "speech_transcription_agent")
    state["speech_transcription_calls"] = state.get("speech_transcription_calls", 0) + 1
    call_number = state["speech_transcription_calls"]

    audio_path = state.get("speech_audio_path") or state.get("audio_file_path") or task_content
    if not audio_path:
        raise ValueError("speech_transcription_agent requires speech_audio_path, audio_file_path, or task content.")
    path = Path(audio_path)
    if not path.is_absolute():
        path = Path(state.get("speech_working_directory", ".")).resolve() / path
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    fields = {
        "model_id": state.get("elevenlabs_stt_model_id", "scribe_v1"),
        "language_code": state.get("speech_language_code", ""),
        "diarize": "true" if state.get("speech_diarize") else "false",
        "tag_audio_events": "true" if state.get("speech_tag_audio_events") else "false",
        "num_speakers": str(state.get("speech_num_speakers", "")) if state.get("speech_num_speakers") else "",
        "timestamps_granularity": state.get("speech_timestamps_granularity", ""),
    }
    keyterms = state.get("speech_keyterms")
    if isinstance(keyterms, list) and keyterms:
        fields["keyterms"] = ",".join(str(item) for item in keyterms)

    result = _multipart_request(
        "/v1/speech-to-text",
        fields,
        "file",
        str(path),
        timeout=int(state.get("elevenlabs_transcription_timeout", 300)),
    )
    transcript_text = result.get("text", "")
    summary = llm_text(
        f"""You are an ElevenLabs speech transcription agent.

Summarize this transcription result.
Highlight the core content, speaker or diarization notes if present, and any quality caveats.

Payload:
{json.dumps(result, indent=2, ensure_ascii=False)[:40000]}
"""
    )
    _write_outputs("speech_transcription_agent", call_number, summary, result)
    if transcript_text:
        write_text_file(f"speech_transcription_agent_{call_number}_transcript.txt", transcript_text)
    state["speech_transcription_result"] = result
    state["speech_transcript_text"] = transcript_text
    state["draft_response"] = summary
    log_task_update("Speech Transcription", f"Transcription pass #{call_number} completed for {path.name}.")
    return publish_agent_output(
        state,
        "speech_transcription_agent",
        summary,
        f"speech_transcription_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )
