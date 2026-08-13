"""Garante um único daemon por repositório."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from types import TracebackType

from devmate.errors import DaemonAlreadyRunningError


def _process_alive(pid: int) -> bool:
    """Detecta um lock órfão deixado por um processo que morreu sem limpar."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Existe, mas pertence a outra conta: tratar como vivo é o lado seguro.
        return True
    except OSError:
        return False
    return True


class InstanceLock:
    """Lockfile com PID, resistente a um encerramento abrupto anterior."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._existing_pid()
        if existing is not None and _process_alive(existing):
            raise DaemonAlreadyRunningError(
                f"A Diana já está ativa neste repositório (PID {existing}). "
                "Encerre a instância anterior antes de iniciar outra."
            )
        # PID ausente, ilegível ou morto: o lock é órfão e pode ser retomado.
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self._acquired = True

    def _existing_pid(self) -> int | None:
        try:
            content = self.path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        try:
            return int(content)
        except ValueError:
            return None

    def release(self) -> None:
        if not self._acquired:
            return
        with contextlib.suppress(OSError):
            self.path.unlink()
        self._acquired = False

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
