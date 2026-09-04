"""Metadados centralizados do produto."""

PACKAGE_NAME = "devmate"
DISPLAY_NAME = "DevMate"
ASSISTANT_NAME = "Diana"
__version__ = "0.1.0"
CONFIG_DIRECTORY = ".devmate"
CONFIG_FILENAME = "config.toml"
DATABASE_FILENAME = "state.db"
DEFAULT_PROVIDER = "mock"
DEFAULT_SPEECH_PROVIDER = "system"
DEFAULT_MAX_FILE_BYTES = 512_000
DEFAULT_MAX_DIFF_CHARS = 80_000
PROMPT_VERSION = "v1"
SOURCE_FILE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".tsx", ".go", ".java", ".rs", ".rb"})
# Diretórios de dependências, cache e build nunca são código do projeto; incluí-los
# facilmente estoura limites (um .venv sozinho já tem milhares de arquivos) e gera
# ruído inútil de eventos pra quem observa o filesystem em tempo real.
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {"venv", "node_modules", "dist", "build", "__pycache__", "site-packages"}
)


def is_excluded_directory(name: str) -> bool:
    return name.startswith(".") or name in EXCLUDED_DIRECTORY_NAMES or name.endswith(".egg-info")
