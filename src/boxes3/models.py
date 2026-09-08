"""The domain model of §4.

Shared by the storage layer and the API. The storage layer speaks these rather than
rows, so swapping the backend stays a new implementation rather than a rewrite (§7.4).

`id` here is the internal integer key. It never reaches a client: the API models of §6
expose `public_id` under the name `id` (§6.0).
"""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from boxes3.tags import normalise

BoxNumber = Annotated[int, Field(ge=1)]
Name = Annotated[str | None, Field(max_length=200)]
Description = Annotated[str | None, Field(max_length=2000)]
Location = Annotated[str | None, Field(max_length=200)]
# Stripped first, then measured, so a title of only spaces fails rather than
# reaching the CHECK constraint in the schema (§4, §7.3).
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Tags = Annotated[list[str], AfterValidator(normalise)]


class User(BaseModel):
    id: int
    username: str
    password_hash: str
    created_at: datetime


class Box(BaseModel):
    id: int
    public_id: str
    user_id: int
    number: BoxNumber
    name: Name = None
    description: Description = None
    location: Location = None
    created_at: datetime
    item_count: int = 0


class NewBox(BaseModel):
    number: BoxNumber
    name: Name = None
    description: Description = None
    location: Location = None


class BoxUpdate(BaseModel):
    """
    A PATCH body (§6.2). Omitted fields are unchanged, explicit `None` clears an
    optional field, which is why the storage layer reads it with `exclude_unset`
    rather than looking for `None`.
    """

    number: BoxNumber | None = None
    name: Name = None
    description: Description = None
    location: Location = None


class Page[T](BaseModel):
    """One page of a collection, plus the `total` across all pages §6.0 requires."""

    entries: list[T]
    total: int
    next_cursor: str | None = None


class BoxSummary(BaseModel):
    """The box embedded in an item (§4). Always present: an item is always in a box."""

    public_id: str
    number: int
    name: Name = None
    location: Location = None


class Item(BaseModel):
    id: int
    public_id: str
    user_id: int
    box: BoxSummary
    title: str
    description: Description = None
    tags: list[str] = []
    image_key: str | None = None
    image_original_type: str | None = None
    created_at: datetime
    updated_at: datetime


class NewItem(BaseModel):
    title: Title
    box_id: str
    description: Description = None
    tags: Tags = []


class ItemUpdate(BaseModel):
    """
    A PATCH body (§6.3). Read with `exclude_unset`, like `BoxUpdate`.

    Setting `box_id` is how an item is moved; there is no separate operation for it.
    """

    title: Title | None = None
    description: Description = None
    tags: Tags | None = None
    box_id: str | None = None


class TagCount(BaseModel):
    tag: str
    count: int
