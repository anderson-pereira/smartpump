from typing import Any, Mapping, Optional, Protocol

from smartpump.domain.recipes import RecipeCatalog, RecipeDocument


class RecipeRepository(Protocol):
    """Persistence operations needed by current and future interfaces."""

    def discover(self, directory=None) -> RecipeCatalog:
        ...

    def get(self, identifier: str) -> RecipeDocument:
        ...

    def create(self, identifier: str, data: Mapping[str, Any]) -> RecipeDocument:
        ...

    def update(
        self,
        identifier: str,
        data: Mapping[str, Any],
        expected_revision: Optional[str],
    ) -> RecipeDocument:
        ...

    def delete(self, identifier: str, expected_revision: str) -> None:
        ...
