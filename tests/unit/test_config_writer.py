from __future__ import annotations

from pathlib import Path

from devmate.config import DEFAULT_CONFIG_TOML
from devmate.config_writer import set_default_scope, set_speech_style, set_speech_voice


def test_set_speech_voice_preserves_comments_and_other_sections(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    set_speech_voice(path, "marin")

    content = path.read_text(encoding="utf-8")
    assert 'voice = "marin"' in content
    # Comentários e outras seções continuam intactos.
    assert "# Configuração local do DevMate. Não armazene chaves neste arquivo." in content
    assert "[language_model.providers.codex]" in content
    assert 'default = "mock"' in content


def test_set_speech_voice_can_also_switch_the_provider(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    set_speech_voice(path, "marin", provider="openai")

    content = path.read_text(encoding="utf-8")
    assert 'voice = "marin"' in content
    assert 'provider = "openai"' in content


def test_set_speech_voice_does_not_touch_provider_when_not_given(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    set_speech_voice(path, "marin")

    content = path.read_text(encoding="utf-8")
    assert 'provider = "system"' in content


def test_set_speech_style_writes_a_new_key(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    set_speech_style(path, "technical_calm")

    assert 'style = "technical_calm"' in path.read_text(encoding="utf-8")


def test_set_default_scope_preserves_the_rest_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    set_default_scope(path, "code")

    content = path.read_text(encoding="utf-8")
    assert 'default_scope = "code"' in content
    assert "[language_model.providers.codex]" in content
    assert 'default = "mock"' in content


def test_writer_creates_the_file_when_it_does_not_exist(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"

    set_speech_voice(path, "cedar")

    assert path.exists()
    assert 'voice = "cedar"' in path.read_text(encoding="utf-8")
