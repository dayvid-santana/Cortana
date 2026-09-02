"""Integração Git somente por argumentos explícitos, sem shell."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from devmate.domain.enums import ChangeStatus
from devmate.domain.models import CommitRecord, DocumentChange
from devmate.errors import CommitNotFoundError, GitCommandError, RepositoryNotFoundError


class SubprocessGit:
    """Único ponto de contato com o executável Git."""

    def __init__(self, root: Path, timeout_seconds: int = 30, executable: str = "git") -> None:
        self.root = root.resolve()
        self.timeout_seconds = timeout_seconds
        self.executable = executable

    @classmethod
    def from_start(cls, start: Path, timeout_seconds: int = 30) -> SubprocessGit:
        probe = cls(start, timeout_seconds=timeout_seconds)
        return cls(probe.discover_root(start), timeout_seconds=timeout_seconds)

    def _run(self, arguments: Sequence[str], check: bool = True) -> str:
        command = [self.executable, *arguments]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitCommandError("Git não foi encontrado no PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError(f"Git excedeu o timeout de {self.timeout_seconds}s.") from exc
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "falha desconhecida"
            raise GitCommandError(f"Falha em git {' '.join(arguments[:2])}: {message}")
        return result.stdout

    def discover_root(self, start: Path) -> Path:
        original_root = self.root
        self.root = start.resolve()
        try:
            output = self._run(["rev-parse", "--show-toplevel"])
        except GitCommandError as exc:
            raise RepositoryNotFoundError(
                "Nenhum repositório Git foi encontrado neste caminho."
            ) from exc
        finally:
            self.root = original_root
        return Path(output.strip()).resolve()

    def common_dir(self) -> Path:
        raw = self._run(["rev-parse", "--git-common-dir"]).strip()
        return (self.root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()

    def current_branch(self) -> str | None:
        branch = self._run(["symbolic-ref", "--quiet", "--short", "HEAD"], check=False).strip()
        return branch or None

    def head(self) -> str:
        try:
            return self._run(["rev-parse", "HEAD"]).strip()
        except GitCommandError as exc:
            raise CommitNotFoundError("O repositório ainda não possui commits.") from exc

    def resolve_commit(self, revision: str) -> str:
        try:
            return self._run(["rev-parse", "--verify", f"{revision}^{{commit}}"]).strip()
        except GitCommandError as exc:
            raise CommitNotFoundError(f"Commit ou referência não encontrada: {revision}") from exc

    def commits(self, revision: str, first_parent: bool = False) -> list[CommitRecord]:
        args = ["rev-list", "--reverse"]
        if first_parent:
            args.append("--first-parent")
        args.append(revision)
        hashes = [line for line in self._run(args).splitlines() if line]
        return [self.commit_metadata(item) for item in hashes]

    def commit_metadata(self, commit_hash: str) -> CommitRecord:
        separator = "\x1f"
        fmt = "%H%x1f%h%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cI%x1f%s%x1f%b%x1f%T"
        fields = (
            self._run(["show", "-s", f"--format={fmt}", commit_hash]).rstrip("\n").split(separator)
        )
        if len(fields) != 10:
            raise GitCommandError(f"Metadados inválidos para o commit {commit_hash[:7]}.")
        return CommitRecord(
            commit_hash=fields[0],
            short_hash=fields[1],
            parent_hashes=tuple(filter(None, fields[2].split())),
            branch_name=self.current_branch(),
            author_name=fields[3],
            author_email=fields[4],
            authored_at=self._parse_time(fields[5]),
            committed_at=self._parse_time(fields[6]),
            subject=fields[7],
            body=fields[8].strip(),
            tree_hash=fields[9],
        )

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value).astimezone(UTC)

    def markdown_changes(self, record: CommitRecord, max_diff_chars: int) -> list[DocumentChange]:
        raw = self._run(
            [
                "diff-tree",
                "--root",
                "-r",
                "--no-commit-id",
                "--name-status",
                "-M",
                "-C",
                record.commit_hash,
            ]
        )
        results: list[DocumentChange] = []
        for line in raw.splitlines():
            fields = line.split("\t")
            status_code = fields[0]
            status = self._status(status_code)
            paths = fields[1:]
            old_path, new_path = self._paths_for_status(status, paths)
            candidate = new_path or old_path
            if candidate is None or Path(candidate).suffix.lower() not in {".md", ".mdx"}:
                continue
            additions, deletions = self._numstat(record, candidate)
            diff = self._diff(record, candidate, max_diff_chars)
            results.append(
                DocumentChange(
                    status=status,
                    old_path=old_path,
                    new_path=new_path,
                    extension=Path(candidate).suffix.lower(),
                    additions=additions,
                    deletions=deletions,
                    diff_text=diff,
                    old_blob_hash=self._blob(record.first_parent_hash, old_path),
                    new_blob_hash=self._blob(record.commit_hash, new_path),
                )
            )
        return results

    @staticmethod
    def _status(code: str) -> ChangeStatus:
        initial = code[0]
        mapping = {
            "A": ChangeStatus.ADDED,
            "M": ChangeStatus.MODIFIED,
            "D": ChangeStatus.DELETED,
            "R": ChangeStatus.RENAMED,
            "C": ChangeStatus.COPIED,
        }
        return mapping.get(initial, ChangeStatus.MODIFIED)

    @staticmethod
    def _paths_for_status(status: ChangeStatus, paths: list[str]) -> tuple[str | None, str | None]:
        if status in {ChangeStatus.RENAMED, ChangeStatus.COPIED} and len(paths) >= 2:
            return paths[0], paths[1]
        if status is ChangeStatus.DELETED:
            return paths[0] if paths else None, None
        return None, paths[0] if paths else None

    def _numstat(self, record: CommitRecord, path: str) -> tuple[int, int]:
        output = self._run(
            ["show", "--format=", "--numstat", record.commit_hash, "--", path], check=False
        )
        first = output.splitlines()[0].split("\t") if output.splitlines() else ["0", "0"]
        return (
            int(first[0]) if first[0].isdigit() else 0,
            int(first[1]) if first[1].isdigit() else 0,
        )

    def _diff(self, record: CommitRecord, path: str, max_chars: int) -> str:
        output = self._run(
            ["show", "--format=", "--no-ext-diff", "--unified=3", record.commit_hash, "--", path],
            check=False,
        )
        if len(output) > max_chars:
            return output[:max_chars] + "\n\n[DIFF TRUNCADO PELO LIMITE CONFIGURADO]\n"
        return output

    def _blob(self, commit_hash: str | None, path: str | None) -> str | None:
        if not commit_hash or not path:
            return None
        output = self._run(["rev-parse", f"{commit_hash}:{path}"], check=False).strip()
        return output if len(output) == 40 else None

    def file_at_commit(self, commit_hash: str, path: str) -> str:
        return self._run(["show", f"{commit_hash}:{path}"])

    def tracked_files(self, commit_hash: str) -> list[str]:
        """Arquivos versionados no commit, sem tocar no diretório de trabalho."""
        output = self._run(["ls-tree", "-r", "--name-only", commit_hash])
        return [item for item in output.splitlines() if item]

    def changed_files(self, revision: str) -> list[str]:
        output = self._run(["diff-tree", "--root", "-r", "--no-commit-id", "--name-only", revision])
        return [item for item in output.splitlines() if item]
