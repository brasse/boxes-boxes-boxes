"""The storage interface, in domain terms (§7.4).

Raising domain exceptions rather than leaking driver errors is half of what keeps the
backend swappable. The other half is that no SQL exists outside an implementation of
this class.

`box_id` arguments are always a box's **public** id. Resolving one to an internal key
happens inside the implementation and nowhere else (§6.0).
"""

from abc import ABC, abstractmethod

from boxes3.models import Box, BoxUpdate, NewBox, Page, User


class UserNotFoundError(Exception): ...


class UsernameTakenError(Exception): ...


class BoxNotFoundError(Exception): ...


class BoxNumberTakenError(Exception): ...


class BoxNotEmptyError(Exception):
    """A box still holding items was deleted without `force` (§6.2)."""

    def __init__(self, item_count: int):
        super().__init__(f"box still holds {item_count} items")
        self.item_count = item_count


class InvalidCursorError(Exception):
    """A pagination cursor the server did not issue, or issued in another format."""


class InventoryDatabase(ABC):
    @abstractmethod
    def create_user(self, username: str, password_hash: str) -> User: ...

    @abstractmethod
    def get_user(self, username: str) -> User: ...

    @abstractmethod
    def set_password(self, username: str, password_hash: str) -> User: ...

    @abstractmethod
    def create_box(self, user_id: int, box: NewBox) -> Box: ...

    @abstractmethod
    def get_box(self, user_id: int, box_id: str) -> Box: ...

    @abstractmethod
    def list_boxes(
        self,
        user_id: int,
        *,
        q: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Box]:
        """
        Ordered by `number` ascending, with `q` matched against number, name and
        location.
        """

    @abstractmethod
    def update_box(self, user_id: int, box_id: str, changes: BoxUpdate) -> Box: ...

    @abstractmethod
    def delete_box(self, user_id: int, box_id: str, *, force: bool = False) -> None:
        """
        Raises `BoxNotEmptyError` unless `force`, in which case the box and everything
        in it go in one transaction (§6.2).
        """

    @abstractmethod
    def next_box_number(self, user_id: int) -> int:
        """
        The lowest unused positive integer. A suggestion, not a reservation (§6.2).
        """

    @abstractmethod
    def box_locations(self, user_id: int) -> list[str]:
        """Distinct non-empty locations already in use, for autocomplete (§6.2)."""
