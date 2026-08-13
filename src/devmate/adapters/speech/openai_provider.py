"""Síntese de fala pela API de áudio da OpenAI.

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

from devmate.adapters.speech.openai_catalog import (
    PROVIDER_NAME,
    available_voices,
    is_known_voice,
    supports_instructions,
    voice_ids,
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

DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_RESPONSE_FORMAT = "mp3"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"

# Presets de estilo; só têm efeito em modelos que aceitam ``instructions``.
STYLE_PRESETS: dict[str, str] = {
    "technical_calm": (
        "Fale em português brasileiro, com ritmo calmo e tom técnico. "
        "Pronuncie identificadores e siglas com clareza, sem traduzi-los."
    ),
    "technical_fast": (
        "Fale em português brasileiro, com ritmo ágil e tom técnico, "
        "mantendo a clareza de identificadores e siglas."
    ),
    "audiobook": (
        "Fale em português brasileiro com entonação de audiolivro, "
        "pausada e expressiva, sem alterar termos técnicos."
    ),
    "concise": "Fale em português brasileiro de forma direta e objetiva.",
    "natural": "Fale em português brasileiro de forma natural e conversacional.",
}


def unknown_voice_error(identifier: str) -> UnknownVoiceError:
    """Erro local, sem gastar uma chamada à API para descobrir a voz inválida."""
    names = ", ".join(voice_ids())
    return UnknownVoiceError(
        f"Voz OpenAI desconhecida: {identifier}\n\nVozes disponíveis:\n{names}"
    )


def _speed_from_rate(rate: int) -> float:
    """Converte palavras por minuto na escala multiplicativa da API (0.25 a 4.0)."""
    return max(0.25, min(4.0, round(rate / 180, 2)))


class OpenAISpeechProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        voice: str | None = None,
        model: str | None = None,
        rate: int = 180,
        style: str | None = None,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        response_format: str = DEFAULT_RESPONSE_FORMAT,
        cache_directory: Path | None = None,
        player: AudioPlayerPort | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.voice = voice
        self.model = model or DEFAULT_MODEL
        self.rate = rate
        self.style = style
        self.api_key_env = api_key_env or DEFAULT_API_KEY_ENV
        self.response_format = response_format
        self.cache_directory = cache_directory
        self.player = player
        self._client_factory = client_factory

    # -- descoberta ---------------------------------------------------------

    def capabilities(self) -> SpeechCapabilities:
        return SpeechCapabilities(
            lists_voices=True,
            supports_voice_selection=True,
            supports_instructions=supports_instructions(self.model),
            supports_rate=True,
            produces_audio_files=True,
            remote=True,
        )

    def list_voices(self) -> list[VoiceInfo]:
        return list(available_voices())

    def available(self) -> tuple[bool, str | None]:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False, "Pacote openai não está instalado."
        if self._client_factory is None and not os.getenv(self.api_key_env):
            return False, f"{self.api_key_env} não está configurada."
        return True, None

    def api_key_configured(self) -> bool:
        return bool(os.getenv(self.api_key_env))

    # -- síntese ------------------------------------------------------------

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise SpeechSynthesisError("Pacote openai não está instalado.") from exc
        return OpenAI()

    def _instructions(self) -> str | None:
        if self.style is None or not supports_instructions(self.model):
            return None
        return STYLE_PRESETS.get(self.style, self.style)

    def cache_path(self, request: SpeechRequest) -> Path | None:
        """Chave determinística; nunca inclui a credencial."""
        if self.cache_directory is None:
            return None
        voice = request.voice or self.voice or ""
        model = request.model or self.model
        rate = request.rate if request.rate is not None else self.rate
        material = " ".join(
            [
                PROVIDER_NAME,
                model,
                voice,
                request.text,
                str(rate),
                self.response_format,
                self._instructions() or "",
            ]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        directory = self.cache_directory / PROVIDER_NAME
        return directory / f"{voice or 'default'}-{digest}.{self.response_format}"

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
            raise SpeechSynthesisError(reason or "Provider de fala OpenAI indisponível.")

        model = request.model or self.model
        rate = request.rate if request.rate is not None else self.rate
        parameters: dict[str, Any] = {
            "model": model,
            "voice": voice,
            "input": request.text,
            "response_format": self.response_format,
            "speed": _speed_from_rate(rate),
        }
        instructions = request.instructions or self._instructions()
        if instructions is not None and supports_instructions(model):
            parameters["instructions"] = instructions

        audio = self._request_audio(parameters, voice)
        if not audio:
            raise SpeechSynthesisError(f"A OpenAI não retornou áudio para a voz '{voice}'.")

        target = destination or self._temporary_path(voice)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
        return SpeechResult(
            provider=PROVIDER_NAME, voice=voice, model=model, audio_path=target, cached=False
        )

    def _temporary_path(self, voice: str) -> Path:
        import tempfile

        directory = Path(tempfile.mkdtemp(prefix="devmate-tts-"))
        return directory / f"{voice}.{self.response_format}"

    def _request_audio(self, parameters: dict[str, Any], voice: str) -> bytes:
        try:
            response = self._client().audio.speech.create(**parameters)
        except Exception as exc:  # o SDK expõe uma árvore própria de exceções
            raise self._translate(exc, voice) from exc
        content = getattr(response, "content", None)
        if isinstance(content, bytes):
            return content
        read = getattr(response, "read", None)
        if callable(read):
            data = read()
            if isinstance(data, bytes):
                return data
        return b""

    def _translate(self, exc: Exception, voice: str) -> SynthesisFailure:
        """Traduz a exceção do SDK em uma mensagem acionável, sem traceback."""
        name = type(exc).__name__
        detail = str(exc).strip() or name
        prefix = f"Não foi possível gerar o áudio da voz '{voice}'.\n\nProvider: OpenAI\nMotivo: "
        if "Authentication" in name or "PermissionDenied" in name:
            return ProviderAuthenticationError(
                f"{prefix}credencial inválida ou sem permissão ({detail})."
            )
        if "RateLimit" in name:
            return SpeechSynthesisError(f"{prefix}limite de requisições atingido ({detail}).")
        if "Timeout" in name:
            return SpeechSynthesisError(f"{prefix}tempo limite excedido ({detail}).")
        if "Connection" in name or "APIConnection" in name:
            return SpeechSynthesisError(f"{prefix}falha de rede ({detail}).")
        if "NotFound" in name:
            return SpeechSynthesisError(
                f"{prefix}modelo '{self.model}' ou voz '{voice}' não disponível ({detail})."
            )
        if "BadRequest" in name:
            return SpeechSynthesisError(
                f"{prefix}pedido rejeitado; verifique se a voz '{voice}' é compatível com o "
                f"modelo '{self.model}' ({detail})."
            )
        return SpeechSynthesisError(f"{prefix}{detail}.")

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
