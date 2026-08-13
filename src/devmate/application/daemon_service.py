"""Daemon residente: aguarda o atalho e conduz uma rodada de voz por vez.

O microfone permanece fechado entre as rodadas. Ele só é aberto depois de um
gatilho explícito, portanto a promessa de captura sob demanda continua válida.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from devmate.application.voice_service import VoiceConversationService, VoiceTurn
from devmate.domain.ports import HotkeyPort
from devmate.errors import DevMateError


@dataclass(frozen=True, slots=True)
class DaemonRound:
    """Resultado de uma rodada; ``error`` mantém o daemon vivo após uma falha."""

    answer: VoiceTurn | None = None
    error: str | None = None


class DaemonService:
    def __init__(
        self,
        hotkey: HotkeyPort,
        voice: VoiceConversationService,
        before_round: Callable[[], None] | None = None,
    ) -> None:
        self.hotkey = hotkey
        self.voice = voice
        # Executado a cada gatilho: é onde o HEAD atual é reindexado.
        self.before_round = before_round

    def run(
        self,
        project_id: int,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
        duration_seconds: int | None = None,
        speak_response: bool = True,
        code_files: list[str] | None = None,
        full_repo: bool = False,
    ) -> Iterator[DaemonRound]:
        while self.hotkey.wait():
            if self.before_round is not None:
                self.before_round()
            try:
                answer = self.voice.listen_and_ask(
                    project_id=project_id,
                    provider_name=provider_name,
                    commit_ref=commit_ref,
                    model=model,
                    duration_seconds=duration_seconds,
                    speak_response=speak_response,
                    code_files=code_files,
                    full_repo=full_repo,
                )
            except DevMateError as exc:
                # Uma rodada falha (silêncio, provider fora do ar) não derruba o daemon:
                # ele precisa continuar disponível para o próximo atalho.
                yield DaemonRound(error=str(exc))
                continue
            yield DaemonRound(answer=answer)
