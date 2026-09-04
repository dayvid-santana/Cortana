"""Síntese de fala pela API REST da ElevenLabs.

A síntese acontece inteiramente no provider remoto e o resultado é um arquivo de
áudio; a reprodução fica a cargo de um ``AudioPlayerPort``. Quando este provider é
selecionado, as vozes instaladas no sistema operacional não participam do fluxo.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from devmate.adapters.speech.elevenlabs_catalog import (
    DEFAULT_MODEL,
    ELEVENLABS_BUILTIN_VOICES,
    PROVIDER_NAME,
    is_known_voice,
)
from devmate.domain.ports import AudioPlayerPort
from devmate.domain.speech import (
    SpeechCapabilities,
    SpeechRequest,
    SpeechResult,
    VoiceInfo,
)
from devmate.errors import (
    ProviderAuthenticationError,
    SpeechSynthesisError,
    UnknownVoiceError,
)

SynthesisFailure = ProviderAuthenticationError | SpeechSynthesisError

DEFAULT_API_KEY_ENV = "ELEVENLABS_API_KEY"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
API_BASE_URL = "https://api.elevenlabs.io/v1"


def unknown_voice_error(identifier: str) -> UnknownVoiceError:
    return UnknownVoiceError(
        f"Voz ElevenLabs desconhecida: {identifier}\n\n"
        "Use `devmate voices list --provider elevenlabs` para ver as opções, ou "
        "confira o id na sua biblioteca em elevenlabs.io/app/voice-library."
    )


def _speed_from_rate(rate: int) -> float:
    """Converte palavras por minuto na escala multiplicativa aceita (0.7 a 1.2)."""
    return max(0.7, min(1.2, round(rate / 180, 2)))


class ElevenLabsSpeechProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        voice: str | None = None,
        model: str | None = None,
        rate: int = 180,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        cache_directory: Path | None = None,
        player: AudioPlayerPort | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.voice = voice
        self.model = model or DEFAULT_MODEL
        self.rate = rate
        self.api_key_env = api_key_env or DEFAULT_API_KEY_ENV
        self.output_format = output_format
        self.cache_directory = cache_directory
        self.player = player
        self._client_factory = client_factory

    # -- descoberta ---------------------------------------------------------

    def capabilities(self) -> SpeechCapabilities:
        return SpeechCapabilities(
            lists_voices=True,
            supports_voice_selection=True,
            supports_instructions=False,
            supports_rate=True,
            produces_audio_files=True,
            remote=True,
        )

    def list_voices(self) -> list[VoiceInfo]:
        available, _ = self.available()
        if not available:
            return list(ELEVENLABS_BUILTIN_VOICES)
        try:
            return self._fetch_voices()
        except Exception:
            # A conta pode estar indisponível; o catálogo local ainda é útil.
            return list(ELEVENLABS_BUILTIN_VOICES)

    def _fetch_voices(self) -> list[VoiceInfo]:
        response = self._client().get(
            f"{API_BASE_URL}/voices", headers={"xi-api-key": self._api_key()}
        )
        response.raise_for_status()
        payload = response.json()
        voices = []
        for entry in payload.get("voices", []):
            voice_id = entry.get("voice_id")
            if not voice_id:
                continue
            voices.append(
                VoiceInfo(
                    id=voice_id,
                    name=entry.get("name", voice_id),
                    provider=PROVIDER_NAME,
                    description=(entry.get("labels") or {}).get("description"),
                    preview_supported=True,
                )
            )
        return voices or list(ELEVENLABS_BUILTIN_VOICES)

    def available(self) -> tuple[bool, str | None]:
        try:
            import httpx  # noqa: F401
        except ImportError:
            return False, "Pacote httpx não está instalado."
        if self._client_factory is None and not os.getenv(self.api_key_env):
            return False, f"{self.api_key_env} não está configurada."
        return True, None

    def api_key_configured(self) -> bool:
        return bool(os.getenv(self.api_key_env))

    def _api_key(self) -> str:
        return os.getenv(self.api_key_env, "")

    # -- síntese ------------------------------------------------------------

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        import httpx

        return httpx.Client(timeout=60.0)

    def cache_path(self, request: SpeechRequest) -> Path | None:
        """Chave determinística; nunca inclui a credencial."""
        if self.cache_directory is None:
            return None
        voice = request.voice or self.voice or ""
        model = request.model or self.model
        rate = request.rate if request.rate is not None else self.rate
        material = " ".join(
            [PROVIDER_NAME, model, voice, request.text, str(rate), self.output_format]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        directory = self.cache_directory / PROVIDER_NAME
        extension = "mp3" if self.output_format.startswith("mp3") else "audio"
        return directory / f"{voice or 'default'}-{digest}.{extension}"

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        voice = request.voice or self.voice
        if voice is None:
            raise UnknownVoiceError(
                "Nenhuma voz selecionada. Use `devmate voices set <voz>` "
                "ou informe --voice na execução."
            )
        if not is_known_voice(voice):
            raise unknown_voice_error(voice)

        destination = self.cache_path(request)
        if destination is not None and destination.exists():
            return SpeechResult(
                provider=PROVIDER_NAME,
                voice=voice,
                model=request.model or self.model,
                audio_path=destination,
                cached=True,
            )

        available, reason = self.available()
        if not available:
            if reason and self.api_key_env in reason:
                raise ProviderAuthenticationError(reason)
            raise SpeechSynthesisError(reason or "Provider de fala ElevenLabs indisponível.")

        model = request.model or self.model
        rate = request.rate if request.rate is not None else self.rate
        payload: dict[str, Any] = {
            "text": request.text,
            "model_id": model,
            "voice_settings": {"speed": _speed_from_rate(rate)},
        }

        audio = self._request_audio(voice, payload)
        if not audio:
            raise SpeechSynthesisError(f"A ElevenLabs não retornou áudio para a voz '{voice}'.")

        target = destination or self._temporary_path(voice)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
        return SpeechResult(
            provider=PROVIDER_NAME, voice=voice, model=model, audio_path=target, cached=False
        )

    def _temporary_path(self, voice: str) -> Path:
        import tempfile

        directory = Path(tempfile.mkdtemp(prefix="devmate-tts-"))
        extension = "mp3" if self.output_format.startswith("mp3") else "audio"
        return directory / f"{voice}.{extension}"

    def _request_audio(self, voice: str, payload: dict[str, Any]) -> bytes:
        try:
            response = self._client().post(
                f"{API_BASE_URL}/text-to-speech/{voice}",
                headers={"xi-api-key": self._api_key()},
                params={"output_format": self.output_format},
                json=payload,
            )
        except Exception as exc:
            raise SpeechSynthesisError(
                f"Não foi possível contatar a ElevenLabs para a voz '{voice}': {exc}"
            ) from exc
        if response.status_code != 200:
            raise self._translate(response, voice)
        content: bytes = response.content
        return content

    def _translate(self, response: Any, voice: str) -> SynthesisFailure:
        """Traduz a resposta HTTP em uma mensagem acionável, sem traceback."""
        status = response.status_code
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        prefix = (
            f"Não foi possível gerar o áudio da voz '{voice}'.\n\nProvider: ElevenLabs\nMotivo: "
        )
        if status in (401, 403):
            return ProviderAuthenticationError(
                f"{prefix}credencial inválida ou sem permissão ({detail})."
            )
        if status == 429:
            return SpeechSynthesisError(f"{prefix}limite de requisições atingido ({detail}).")
        if status == 404:
            return SpeechSynthesisError(f"{prefix}voz '{voice}' não encontrada ({detail}).")
        return SpeechSynthesisError(f"{prefix}{detail} (HTTP {status}).")

    # -- reprodução ---------------------------------------------------------

    def speak(self, text: str) -> None:
        result = self.synthesize(SpeechRequest(text=text, voice=self.voice))
        if result.audio_path is None:
            return
        if self.player is None:
            raise SpeechSynthesisError(
                "Nenhum player de áudio configurado para reproduzir a síntese remota."
            )
        self.player.play(result.audio_path)

    def stop(self) -> None:
        """A reprodução é síncrona por arquivo; não há stream a interromper."""
        return None
