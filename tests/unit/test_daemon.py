from __future__ import annotations

import os
from pathlib import Path

import pytest

from devmate.adapters.hotkey.windows_hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    parse_hotkey,
)
from devmate.application.conversation_service import Answer
from devmate.application.daemon_service import DaemonService
from devmate.application.instance_lock import InstanceLock
from devmate.application.voice_service import VoiceAnswer
from devmate.domain.models import LLMResponse
from devmate.errors import (
    DaemonAlreadyRunningError,
    HotkeyUnavailableError,
    SpeechRecognitionUnavailableError,
)


def test_parse_hotkey_builds_modifiers_and_virtual_key() -> None:
    modifiers, virtual_key = parse_hotkey("ctrl+alt+d")

    assert modifiers == MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
    assert virtual_key == ord("D")


def test_parse_hotkey_accepts_named_keys_and_is_case_insensitive() -> None:
    modifiers, virtual_key = parse_hotkey("CTRL+SHIFT+F4")

    assert modifiers == MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
    assert virtual_key == 0x73


def test_parse_hotkey_requires_a_modifier() -> None:
    # Sem modificador o atalho sequestraria uma tecla comum do sistema.
    with pytest.raises(HotkeyUnavailableError, match="ao menos um modificador"):
        parse_hotkey("d")


@pytest.mark.parametrize("combination", ["ctrl+alt+naoexiste", "hyper+d", ""])
def test_parse_hotkey_rejects_unknown_combinations(combination: str) -> None:
    with pytest.raises(HotkeyUnavailableError):
        parse_hotkey(combination)


class ScriptedHotkey:
    """Dispara um número fixo de vezes e depois encerra o daemon."""

    name = "scripted"

    def __init__(self, triggers: int) -> None:
        self.remaining = triggers

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def wait(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


class StubVoice:
    def __init__(self, failures: int = 0) -> None:
        self.calls = 0
        self.failures = failures

    def listen_and_ask(self, **kwargs: object) -> VoiceAnswer:
        self.calls += 1
        if self.calls <= self.failures:
            raise SpeechRecognitionUnavailableError("Nenhuma fala foi reconhecida.")
        return VoiceAnswer(
            transcript=f"pergunta {self.calls}",
            answer=Answer("e" * 40, LLMResponse(f"resposta {self.calls}")),
        )


def test_daemon_runs_one_round_per_trigger() -> None:
    voice = StubVoice()
    service = DaemonService(ScriptedHotkey(3), voice)  # type: ignore[arg-type]

    rounds = list(service.run(1, "mock"))

    assert [r.answer.transcript for r in rounds if r.answer] == [
        "pergunta 1",
        "pergunta 2",
        "pergunta 3",
    ]


def test_daemon_survives_a_failed_round_and_keeps_serving() -> None:
    voice = StubVoice(failures=1)
    service = DaemonService(ScriptedHotkey(2), voice)  # type: ignore[arg-type]

    rounds = list(service.run(1, "mock"))

    assert rounds[0].error == "Nenhuma fala foi reconhecida."
    assert rounds[0].answer is None
    # O daemon continuou disponível para o gatilho seguinte.
    assert rounds[1].answer is not None
    assert rounds[1].answer.transcript == "pergunta 2"


def test_daemon_reindexes_before_every_round() -> None:
    calls: list[int] = []
    service = DaemonService(
        ScriptedHotkey(2),  # type: ignore[arg-type]
        StubVoice(),  # type: ignore[arg-type]
        before_round=lambda: calls.append(1),
    )

    list(service.run(1, "mock"))

    assert len(calls) == 2


def test_instance_lock_blocks_a_second_live_daemon(tmp_path: Path) -> None:
    path = tmp_path / "daemon.lock"
    first = InstanceLock(path)
    first.acquire()

    with pytest.raises(DaemonAlreadyRunningError, match=str(os.getpid())):
        InstanceLock(path).acquire()

    first.release()
    assert not path.exists()


def test_instance_lock_reclaims_a_lock_left_by_a_dead_process(tmp_path: Path) -> None:
    path = tmp_path / "daemon.lock"
    # PID inexistente simula um daemon encerrado abruptamente.
    path.write_text("999999", encoding="utf-8")

    lock = InstanceLock(path)
    lock.acquire()

    assert path.read_text(encoding="utf-8") == str(os.getpid())
    lock.release()


def test_instance_lock_reclaims_a_corrupted_lockfile(tmp_path: Path) -> None:
    path = tmp_path / "daemon.lock"
    path.write_text("nao é um pid", encoding="utf-8")

    lock = InstanceLock(path)
    lock.acquire()

    assert path.read_text(encoding="utf-8") == str(os.getpid())
    lock.release()
