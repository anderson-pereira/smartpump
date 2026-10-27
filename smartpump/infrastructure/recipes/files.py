import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from smartpump.domain.recipes import (
    ExternalRecipe,
    RecipeAlreadyExistsError,
    RecipeCatalog,
    RecipeConfigError,
    RecipeConflictError,
    RecipeDocument,
    RecipeNotFoundError,
    parse_recipe_config,
)
from smartpump.settings import DEFAULT_RECIPE_DIRECTORY


PathInput = Union[str, Path]


def _decode_recipe(recipe_path: Path, content: bytes) -> Mapping[str, Any]:
    try:
        data = json.loads(content.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise RecipeConfigError(
            f"Arquivo de receita não está codificado em UTF-8: {recipe_path}."
        ) from error
    except json.JSONDecodeError as error:
        raise RecipeConfigError(
            f"JSON inválido em {recipe_path}, linha {error.lineno}: {error.msg}."
        ) from error
    if not isinstance(data, dict):
        raise RecipeConfigError("A raiz da receita deve ser um objeto JSON.")
    return data


def load_recipe_config(path: PathInput) -> ExternalRecipe:
    recipe_path = Path(path).expanduser()
    try:
        content = recipe_path.read_bytes()
    except FileNotFoundError as error:
        raise RecipeConfigError(
            f"Arquivo de receita não encontrado: {recipe_path}"
        ) from error
    except OSError as error:
        raise RecipeConfigError(f"Não foi possível ler {recipe_path}: {error}") from error

    data = _decode_recipe(recipe_path, content)
    return parse_recipe_config(data, source=recipe_path.resolve())


class FileRecipeRepository:
    """Validated and atomic JSON persistence for static recipe definitions."""

    def __init__(self, directory: PathInput = DEFAULT_RECIPE_DIRECTORY):
        self.directory = Path(directory).expanduser().resolve()
        self._lock = threading.RLock()

    def discover(self, directory=None) -> RecipeCatalog:
        recipe_directory = (
            self.directory
            if directory is None
            else Path(directory).expanduser().resolve()
        )
        if not recipe_directory.exists():
            return RecipeCatalog((), (), str(recipe_directory))
        if not recipe_directory.is_dir():
            return RecipeCatalog(
                (),
                ((str(recipe_directory), "O caminho de receitas não é uma pasta."),),
                str(recipe_directory),
            )

        recipes = []
        errors = []
        for recipe_path in sorted(
            recipe_directory.glob("*.json"),
            key=lambda path: path.name.casefold(),
        ):
            try:
                recipes.append(load_recipe_config(recipe_path))
            except RecipeConfigError as error:
                errors.append((str(recipe_path), str(error)))
        return RecipeCatalog(tuple(recipes), tuple(errors), str(recipe_directory))

    def get(self, identifier: str) -> RecipeDocument:
        with self._lock:
            recipe_path = self._resolve_identifier(identifier)
            try:
                content = recipe_path.read_bytes()
            except FileNotFoundError as error:
                raise RecipeNotFoundError(
                    f"Receita não encontrada: {identifier}"
                ) from error
            except OSError as error:
                raise RecipeConfigError(
                    f"Não foi possível ler {recipe_path}: {error}"
                ) from error
            return self._document(recipe_path, content)

    def create(self, identifier: str, data: Mapping[str, Any]) -> RecipeDocument:
        with self._lock:
            recipe_path = self._resolve_identifier(identifier)
            if recipe_path.exists():
                raise RecipeAlreadyExistsError(f"A receita já existe: {identifier}")
            content = self._validated_content(recipe_path, data)
            self._atomic_write(recipe_path, content, require_existing=False)
            return self._document(recipe_path, content)

    def update(
        self,
        identifier: str,
        data: Mapping[str, Any],
        expected_revision: Optional[str],
    ) -> RecipeDocument:
        with self._lock:
            recipe_path = self._resolve_identifier(identifier)
            current = self.get(identifier)
            if expected_revision is not None and current.revision != expected_revision:
                raise RecipeConflictError(
                    "A receita foi modificada desde a leitura; recarregue antes de salvar."
                )
            content = self._validated_content(recipe_path, data)
            self._atomic_write(recipe_path, content, require_existing=True)
            return self._document(recipe_path, content)

    def delete(self, identifier: str, expected_revision: str) -> None:
        with self._lock:
            recipe_path = self._resolve_identifier(identifier)
            current = self.get(identifier)
            if current.revision != expected_revision:
                raise RecipeConflictError(
                    "A receita foi modificada desde a leitura; recarregue antes de excluir."
                )
            try:
                recipe_path.unlink()
            except FileNotFoundError as error:
                raise RecipeNotFoundError(
                    f"Receita não encontrada: {identifier}"
                ) from error

    def _resolve_identifier(self, identifier: str) -> Path:
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("O identificador da receita não pode ser vazio.")
        candidate = Path(identifier)
        if candidate.name != identifier or candidate.suffix.lower() != ".json":
            raise ValueError(
                "O identificador deve ser apenas um nome de arquivo terminado em .json."
            )
        return self.directory / candidate.name

    @staticmethod
    def _revision(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _document(self, recipe_path: Path, content: bytes) -> RecipeDocument:
        data = _decode_recipe(recipe_path, content)
        recipe = parse_recipe_config(data, source=recipe_path)
        return RecipeDocument(
            identifier=recipe_path.name,
            revision=self._revision(content),
            data=data,
            recipe=recipe,
        )

    @staticmethod
    def _validated_content(recipe_path: Path, data: Mapping[str, Any]) -> bytes:
        payload = dict(data)
        parse_recipe_config(payload, source=recipe_path)
        try:
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )
        except (TypeError, ValueError) as error:
            raise RecipeConfigError(f"A receita não pode ser serializada: {error}") from error
        return (serialized + "\n").encode("utf-8")

    def _atomic_write(
        self,
        recipe_path: Path,
        content: bytes,
        require_existing: bool,
    ) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if require_existing and not recipe_path.exists():
            raise RecipeNotFoundError(f"Receita não encontrada: {recipe_path.name}")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{recipe_path.stem}.",
            suffix=".tmp",
            dir=self.directory,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            if require_existing:
                os.replace(temporary_path, recipe_path)
            else:
                try:
                    os.link(temporary_path, recipe_path)
                except FileExistsError as error:
                    raise RecipeAlreadyExistsError(
                        f"A receita já existe: {recipe_path.name}"
                    ) from error
        finally:
            if temporary_path.exists():
                temporary_path.unlink()


def discover_recipe_configs(directory=None) -> RecipeCatalog:
    return FileRecipeRepository().discover(directory)
