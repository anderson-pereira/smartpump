import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple, cast

from smartpump.settings import VALVE_CHANNEL_COUNT


RecipeStep = Tuple[int, str, float, Optional[float]]


@dataclass(frozen=True)
class ExternalRecipe:
    name: str
    description: str
    steps: Tuple[RecipeStep, ...]
    cycle_count: Optional[int]
    source: str


@dataclass(frozen=True)
class RecipeCatalog:
    recipes: Tuple[ExternalRecipe, ...]
    errors: Tuple[Tuple[str, str], ...]
    directory: str


@dataclass(frozen=True)
class RecipeDocument:
    """Editable persisted recipe plus its optimistic-lock revision."""

    identifier: str
    revision: str
    data: Mapping[str, Any]
    recipe: ExternalRecipe

MAX_RECIPE_STEPS = 10000
MAX_RECIPE_STEPS_LABEL = f"{MAX_RECIPE_STEPS:,}".replace(",", ".")
MAX_RECIPE_DURATION_SECONDS = 7 * 24 * 60 * 60
MAX_RECIPE_NESTING = 20


class RecipeConfigError(ValueError):
    """Raised when an external recipe does not match the supported format."""


class RecipeNotFoundError(FileNotFoundError):
    """Raised when a recipe identifier is not present in the repository."""


class RecipeAlreadyExistsError(FileExistsError):
    """Raised when creation would overwrite a persisted recipe."""


class RecipeConflictError(RuntimeError):
    """Raised when an update targets an outdated recipe revision."""


def normalize_recipe_step(step: Sequence[Any]) -> RecipeStep:
    """Return channel, solution, duration and optional flow rate."""
    if len(step) == 3:
        channel, solution, duration = step
        return cast(RecipeStep, (channel, solution, duration, None))
    if len(step) == 4:
        return cast(RecipeStep, tuple(step))
    raise ValueError("Cada etapa deve possuir três ou quatro campos.")


def _validate_cycle_count(value, path="'cycles'", allow_continuous=True):
    if value is None and allow_continuous:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        suffix = " ou null" if allow_continuous else ""
        raise RecipeConfigError(
            f"{path}: 'cycles' deve ser um inteiro positivo{suffix}."
        )
    return value


def _validate_flow_rate(value, path):
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise RecipeConfigError(
            f"{path}: 'flow_rate_ml_min' deve ser um número finito ou null."
        )
    return value


def _validate_step(
    step,
    path,
    inherited_flow_rate,
    depth=1,
) -> Tuple[RecipeStep, ...]:
    if not isinstance(step, dict):
        raise RecipeConfigError(f"{path}: deve ser um objeto JSON.")

    if "steps" in step:
        if depth > MAX_RECIPE_NESTING:
            raise RecipeConfigError(
                f"{path}: a receita excede {MAX_RECIPE_NESTING} níveis de blocos."
            )

        allowed_fields = {"name", "cycles", "flow_rate_ml_min", "steps"}
        unknown_fields = set(step) - allowed_fields
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise RecipeConfigError(f"{path}: campos desconhecidos: {fields}.")

        name = step.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise RecipeConfigError(f"{path}: 'name' deve ser um texto não vazio.")

        cycle_count = _validate_cycle_count(
            step.get("cycles", 1),
            path,
            allow_continuous=False,
        )
        flow_rate = (
            _validate_flow_rate(step["flow_rate_ml_min"], path)
            if "flow_rate_ml_min" in step
            else inherited_flow_rate
        )
        raw_steps = step["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise RecipeConfigError(f"{path}: 'steps' deve ser uma lista não vazia.")

        normalized_steps = []
        for index, child in enumerate(raw_steps, start=1):
            child_path = f"{path} > etapa {index}"
            normalized_steps.extend(
                _validate_step(child, child_path, flow_rate, depth + 1)
            )
            if len(normalized_steps) > MAX_RECIPE_STEPS:
                raise RecipeConfigError(
                    f"{path}: o bloco excede o limite de "
                    f"{MAX_RECIPE_STEPS_LABEL} etapas executáveis."
                )

        expanded_count = len(normalized_steps) * cycle_count
        if expanded_count > MAX_RECIPE_STEPS:
            raise RecipeConfigError(
                f"{path}: o bloco excede o limite de "
                f"{MAX_RECIPE_STEPS_LABEL} etapas executáveis após as repetições."
            )
        return tuple(normalized_steps) * cycle_count

    required_fields = {"channel", "solution", "duration_minutes"}
    allowed_fields = required_fields | {"flow_rate_ml_min"}
    unknown_fields = set(step) - allowed_fields
    missing_fields = required_fields - set(step)
    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise RecipeConfigError(f"{path}: campos desconhecidos: {fields}.")
    if missing_fields:
        fields = ", ".join(sorted(missing_fields))
        raise RecipeConfigError(f"{path}: campos obrigatórios ausentes: {fields}.")

    channel = step["channel"]
    if (
        isinstance(channel, bool)
        or not isinstance(channel, int)
        or channel not in range(1, VALVE_CHANNEL_COUNT + 1)
    ):
        raise RecipeConfigError(
            f"{path}: 'channel' deve estar entre 1 e "
            f"{VALVE_CHANNEL_COUNT}."
        )

    solution = step["solution"]
    if not isinstance(solution, str) or not solution.strip():
        raise RecipeConfigError(f"{path}: 'solution' não pode ser vazia.")

    duration = step["duration_minutes"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise RecipeConfigError(
            f"{path}: 'duration_minutes' deve ser um número positivo."
        )

    flow_rate = (
        _validate_flow_rate(step["flow_rate_ml_min"], path)
        if "flow_rate_ml_min" in step
        else inherited_flow_rate
    )

    return ((channel, solution.strip(), duration, flow_rate),)


def parse_recipe_config(
    data: Mapping[str, Any],
    source="<memória>",
) -> ExternalRecipe:
    if not isinstance(data, dict):
        raise RecipeConfigError("A raiz da receita deve ser um objeto JSON.")

    allowed_fields = {
        "schema_version",
        "name",
        "description",
        "cycles",
        "flow_rate_ml_min",
        "steps",
    }
    unknown_fields = set(data) - allowed_fields
    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise RecipeConfigError(f"Campos desconhecidos na receita: {fields}.")

    if data.get("schema_version", 1) != 1:
        raise RecipeConfigError("Apenas 'schema_version' 1 é suportada.")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RecipeConfigError("'name' deve ser um texto não vazio.")

    description = data.get("description", "")
    if not isinstance(description, str):
        raise RecipeConfigError("'description' deve ser um texto.")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RecipeConfigError("'steps' deve ser uma lista não vazia.")
    default_flow_rate = _validate_flow_rate(
        data.get("flow_rate_ml_min"),
        "Receita",
    )
    normalized_steps = []
    for index, step in enumerate(raw_steps, start=1):
        normalized_steps.extend(
            _validate_step(
                step,
                f"Etapa {index}",
                default_flow_rate,
            )
        )
        if len(normalized_steps) > MAX_RECIPE_STEPS:
            raise RecipeConfigError(
                f"A receita excede o limite de {MAX_RECIPE_STEPS_LABEL} "
                "etapas executáveis após as repetições."
            )

    steps = tuple(normalized_steps)
    cycle_count = _validate_cycle_count(data.get("cycles", 1), "Receita")

    duration_per_cycle = sum(step[2] * 60 for step in steps)
    if cycle_count is not None:
        total_duration = duration_per_cycle * cycle_count
        if total_duration > MAX_RECIPE_DURATION_SECONDS:
            raise RecipeConfigError("A duração programada excede o limite de 7 dias.")

    return ExternalRecipe(
        name=name.strip(),
        description=description.strip(),
        steps=steps,
        cycle_count=cycle_count,
        source=str(source),
    )
