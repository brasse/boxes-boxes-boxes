"""The storage interface, in domain terms (§7.4).

Raising domain exceptions rather than leaking driver errors is half of what keeps the
backend swappable. The other half is that no SQL exists outside an implementation of
this class.

**Every identifier here is an external one**: `username` for the owner, `public_id` for
everything else. Internal integer keys do not appear in this interface and therefore
cannot reach a router, a log line or an error message. Resolving an external identifier
to an internal key happens inside the implementation and nowhere else (§6.0, §7.4).
"""

from abc import ABC, abstractmethod

from boxes3.models import (
    Box,
    BoxUpdate,
    Item,
    ItemUpdate,
    NewBox,
    NewItem,
    Page,
    TagCount,
    User,
)


class UserNotFoundError(Exception): ...


class UsernameTakenError(Exception): ...


class BoxNotFoundError(Exception): ...


class BoxNumberTakenError(Exception): ...


class ItemNotFoundError(Exception): ...


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
    def create_box(self, username: str, box: NewBox) -> Box: ...

    @abstractmethod
    def get_box(self, username: str, box_id: str) -> Box: ...

    @abstractmethod
    def list_boxes(
        self,
        username: str,
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
    def update_box(self, username: str, box_id: str, changes: BoxUpdate) -> Box: ...

    @abstractmethod
    def delete_box(self, username: str, box_id: str, *, force: bool = False) -> None:
        """
        Raises `BoxNotEmptyError` unless `force`, in which case the box and everything
        in it go in one transaction (§6.2).
        """

    @abstractmethod
    def next_box_number(self, username: str) -> int:
        """
        The lowest unused positive integer. A suggestion, not a reservation (§6.2).
        """

    @abstractmethod
    def box_locations(self, username: str) -> list[str]:
        """Distinct non-empty locations already in use, for autocomplete (§6.2)."""

    @abstractmethod
    def create_item(self, username: str, item: NewItem) -> Item:
        """Raises `BoxNotFoundError` if `item.box_id` names no box of this user."""

    @abstractmethod
    def get_item(self, username: str, item_id: str) -> Item: ...

    @abstractmethod
    def update_item(self, username: str, item_id: str, changes: ItemUpdate) -> Item:
        """
        Setting `box_id` moves the item, which is why there is no separate move (§6.3).
        """

    @abstractmethod
    def delete_item(self, username: str, item_id: str) -> None:
        """The item's blobs are deliberately left in place (§7.6)."""

    @abstractmethod
    def search_items(
        self,
        username: str,
        *,
        q: str | None = None,
        tags: list[str] | None = None,
        box_id: str | None = None,
        has_image: bool | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Item]:
        """
        Search, per the three rules of §6.3.

        `q` is semantic, not syntactic: it is a free-text query and the server decides
        what it matches. Callers never build query syntax, so widening what it covers
        is not a breaking change.

        Results come back in server-defined order and callers must not re-sort. Today
        that order is `updated_at` descending.

        `tag` is conjunctive: an item must carry every tag given, so a tag that could
        never have been stored is rejected rather than ignored: dropping it would widen
        the search instead of correctly matching nothing. Structured filters stay
        separate from `q` so that adding one later is purely additive.
        """

    @abstractmethod
    def list_tags(self, username: str) -> list[TagCount]:
        """Every tag in use with its count, ordered by count descending (§6.5)."""
