"""Síntese de fala pelo Edge TTS (serviço de voz do Microsoft Edge, não-oficial).

Gratuito e sem chave de API, mas depende de rede e de um serviço não documentado
oficialmente pela Microsoft — pode parar de funcionar sem aviso. A síntese
acontece no serviço remoto e o resultado é um arquivo de áudio; a reprodução
fica a cargo de um ``AudioPlayerPort``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from devmate.adapters.speech.edge_catalog import (
    EDGE_BUILTIN_VOICES,
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
from devmate.errors import SpeechSynthesisError, UnknownVoiceError

DEFAULT_VOICE = "pt-BR-FranciscaNeural"


def unknown_voice_error(identifier: str) -> UnknownVoiceError:
    names = ", ".join(voice.id for voice in EDGE_BUILTIN_VOICES)
    return UnknownVoiceError(f"Voz Edge desconhecida: {identifier}\n\nVozes conhecidas:\n{names}")


def _rate_percent(rate: int, baseline: int = 180) -> str:
    """Converte palavras por minuto num percentual relativo, formato aceito pelo Edge."""
    delta = round((rate - baseline) / baseline * 100)
    delta = max(-50, min(100, delta))
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta}%"


class EdgeSpeechProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        voice: str | None = None,
        rate: int = 180,
        cache_directory: Path | None = None,
        player: AudioPlayerPort | None = None,
        communicate_factory: Callable[[str, str, str], Any] | None = None,
        voice_lister: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.cache_directory = cache_directory
        self.player = player
        self._communicate_factory = communicate_factory
        self._voice_lister = voice_lister

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
        try:
            return self._fetch_voices()
        except Exception:
            return list(EDGE_BUILTIN_VOICES)

    def _fetch_voices(self) -> list[VoiceInfo]:
        entries = self._list_raw_voices()
        voices = [
            VoiceInfo(
                id=entry["ShortName"],
                name=entry["ShortName"],
                provider=PROVIDER_NAME,
                language=entry.get("Locale"),
                preview_supported=True,
            )
            for entry in entries
            if str(entry.get("Locale", "")).startswith("pt-BR")
        ]
        return voices or list(EDGE_BUILTIN_VOICES)

    def _list_raw_voices(self) -> list[dict[str, Any]]:
        if self._voice_lister is not None:
            return self._voice_lister()
        import asyncio
        from typing import cast

        import edge_tts

        result = asyncio.run(edge_tts.list_voices())
        return cast("list[dict[str, Any]]", result)

    def available(self) -> tuple[bool, str | None]:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, "Pacote edge-tts não está instalado."
        return True, None

    # -- síntese ------------------------------------------------------------

    def cache_path(self, request: SpeechRequest) -> Path | None:
        if self.cache_directory is None:
            return None
        voice = request.voice or self.voice or DEFAULT_VOICE
        rate = request.rate if request.rate is not None else self.rate
        material = " ".join([PROVIDER_NAME, voice, request.text, str(rate)])
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        directory = self.cache_directory / PROVIDER_NAME
        return directory / f"{voice}-{digest}.mp3"

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        voice = request.voice or self.voice or DEFAULT_VOICE
        if not is_known_voice(voice):
            raise unknown_voice_error(voice)

        destination = self.cache_path(request)
        if destination is not None and destination.exists():
            return SpeechResult(
                provider=PROVIDER_NAME, voice=voice, audio_path=destination, cached=True
            )

        available, reason = self.available()
        if not available:
            raise SpeechSynthesisError(reason or "Provider de fala Edge indisponível.")

        rate = request.rate if request.rate is not None else self.rate
        target = destination or self._temporary_path(voice)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._synthesize_to_file(request.text, voice, _rate_percent(rate), target)

        if not target.exists() or target.stat().st_size == 0:
            raise SpeechSynthesisError(f"O Edge TTS não retornou áudio para a voz '{voice}'.")
        return SpeechResult(provider=PROVIDER_NAME, voice=voice, audio_path=target, cached=False)

    def _synthesize_to_file(self, text: str, voice: str, rate: str, target: Path) -> None:
        if self._communicate_factory is not None:
            factory = self._communicate_factory
        else:
            try:
                import edge_tts
            except ImportError as exc:
                raise SpeechSynthesisError("Pacote edge-tts não está instalado.") from exc
            factory = lambda t, v, r: edge_tts.Communicate(t, v, rate=r)  # noqa: E731

        try:
            factory(text, voice, rate).save_sync(str(target))
        except Exception as exc:  # o serviço não é oficial; falhas variam de forma
            name = type(exc).__name__
            raise SpeechSynthesisError(
                f"Não foi possível gerar o áudio da voz '{voice}'.\n\n"
                f"Provider: Edge TTS\nMotivo: {name}: {exc}"
            ) from exc

    def _temporary_path(self, voice: str) -> Path:
        import tempfile

        directory = Path(tempfile.mkdtemp(prefix="devmate-tts-"))
        return directory / f"{voice}.mp3"

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
