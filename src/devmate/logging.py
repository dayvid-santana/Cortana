"""Logging mínimo, estruturado e sem conteúdo de repositório por padrão."""

from __future__ import annotations

import logging
import uuid


def configure_logging(debug: bool = False) -> str:
    run_id = str(uuid.uuid4())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(asctime)s %(levelname)s run_id=" + run_id + " %(name)s %(message)s",
    )
    return run_id
