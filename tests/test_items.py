"""Items in the storage layer (§6.3, §6.5)."""

import pytest
from sqlalchemy import update

from boxes3.db.interface import (
    BoxNotFoundError,
    InvalidCursorError,
    ItemNotFoundError,
)
from boxes3.db.schema import items
from boxes3.db.sqlite import SqliteInventoryDatabase
from boxes3.models import Box, Item, ItemUpdate, NewBox, NewItem


@pytest.fixture
def box(db, username):
    return db.create_box(username, NewBox(number=1, name="Tools", location="Attic"))


def add(
    db: SqliteInventoryDatabase, username: str, box: Box, title: str, **values
) -> Item:
    return db.create_item(
        username, NewItem(title=title, box_id=box.public_id, **values)
    )


def set_row(db: SqliteInventoryDatabase, item: Item, **values) -> None:
    """
    Write columns the interface does not expose yet.

    `updated_at` is set directly so ordering tests do not depend on how fast the
    machine happens to be, and `image_key` because images arrive in step 2.4.
    """
    with db.engine.begin() as connection:
        connection.execute(update(items).where(items.c.id == item.id).values(**values))


# Creating and reading


def test_an_item_round_trips(db: SqliteInventoryDatabase, username: str, box: Box):
    created = add(db, username, box, "Cordless drill", description="Makita")

    fetched = db.get_item(username, created.public_id)
    assert fetched.title == "Cordless drill"
    assert fetched.description == "Makita"
    assert fetched.tags == []
    assert fetched.image_key is None


def test_the_title_is_trimmed(db: SqliteInventoryDatabase, username: str, box: Box):
    assert add(db, username, box, "  Cordless drill  ").title == "Cordless drill"


def test_tags_are_normalised_on_the_way_in(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill", tags=["Tools", " POWER ", "tools"])

    assert db.get_item(username, item.public_id).tags == ["power", "tools"]


def test_the_box_is_embedded(db: SqliteInventoryDatabase, username: str, box: Box):
    item = add(db, username, box, "Drill")

    assert item.box.public_id == box.public_id
    assert item.box.number == 1
    assert item.box.name == "Tools"
    assert item.box.location == "Attic"


def test_public_ids_are_sixteen_characters(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    assert len(add(db, username, box, "Drill").public_id) == 16


def test_creating_into_an_unknown_box_raises(
    db: SqliteInventoryDatabase, username: str
):
    with pytest.raises(BoxNotFoundError):
        db.create_item(username, NewItem(title="Drill", box_id="nope"))


def test_creating_into_another_users_box_raises(
    db: SqliteInventoryDatabase, username: str
):
    other = db.create_user("other", "hash").username
    theirs = db.create_box(other, NewBox(number=1))

    with pytest.raises(BoxNotFoundError):
        db.create_item(username, NewItem(title="Drill", box_id=theirs.public_id))


def test_an_unknown_item_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(ItemNotFoundError):
        db.get_item(username, "nope")


def test_another_users_item_is_not_found(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    other = db.create_user("other", "hash").username
    theirs = db.create_box(other, NewBox(number=1))
    mine = add(db, username, box, "Drill")
    add(db, other, theirs, "Their drill")

    assert db.get_item(username, mine.public_id).title == "Drill"
    with pytest.raises(ItemNotFoundError):
        db.get_item(other, mine.public_id)


# Updating and moving


def test_an_omitted_field_is_left_alone(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill", description="Makita", tags=["tools"])

    updated = db.update_item(username, item.public_id, ItemUpdate(title="Hammer"))

    assert updated.title == "Hammer"
    assert updated.description == "Makita"
    assert updated.tags == ["tools"]


def test_an_explicit_null_clears_the_description(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill", description="Makita")

    updated = db.update_item(username, item.public_id, ItemUpdate(description=None))

    assert updated.description is None


def test_tags_are_replaced_wholesale(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill", tags=["tools", "power"])

    updated = db.update_item(username, item.public_id, ItemUpdate(tags=["garden"]))

    assert updated.tags == ["garden"]


def test_tags_can_be_emptied(db: SqliteInventoryDatabase, username: str, box: Box):
    item = add(db, username, box, "Drill", tags=["tools"])

    assert db.update_item(username, item.public_id, ItemUpdate(tags=[])).tags == []


def test_an_update_bumps_updated_at(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill")
    set_row(db, item, updated_at="2020-01-01T00:00:00+00:00")
    stale = db.get_item(username, item.public_id)

    updated = db.update_item(username, item.public_id, ItemUpdate(title="Hammer"))

    assert updated.updated_at > stale.updated_at
    assert updated.created_at == stale.created_at


def test_an_empty_update_changes_nothing(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill")

    assert db.update_item(username, item.public_id, ItemUpdate()) == item


def test_setting_box_id_moves_the_item(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    """Moving an item is changing its box, not a separate operation (§6.3)."""
    cellar = db.create_box(username, NewBox(number=2, location="Cellar"))
    item = add(db, username, box, "Drill")

    moved = db.update_item(
        username, item.public_id, ItemUpdate(box_id=cellar.public_id)
    )

    assert moved.box.number == 2
    assert moved.box.location == "Cellar"
    assert db.get_box(username, box.public_id).item_count == 0
    assert db.get_box(username, cellar.public_id).item_count == 1


def test_moving_to_an_unknown_box_raises(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill")

    with pytest.raises(BoxNotFoundError):
        db.update_item(username, item.public_id, ItemUpdate(box_id="nope"))


def test_updating_an_unknown_item_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(ItemNotFoundError):
        db.update_item(username, "nope", ItemUpdate(title="Hammer"))


# Deleting


def test_deleting_removes_the_item_and_its_tags(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    item = add(db, username, box, "Drill", tags=["tools"])

    db.delete_item(username, item.public_id)

    with pytest.raises(ItemNotFoundError):
        db.get_item(username, item.public_id)
    assert db.list_tags(username) == []
    assert db.get_box(username, box.public_id).item_count == 0


def test_deleting_an_unknown_item_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(ItemNotFoundError):
        db.delete_item(username, "nope")


# The search contract of §10.
#
# These assert behaviour rather than implementation: this query finds that item,
# filters compose, tag is conjunctive, order is server-defined. They are written to
# survive `q` moving from LIKE to FTS5 unchanged. If a change here is needed to make
# that upgrade pass, the upgrade has changed the contract and needs a decision, not a
# quiet edit to the test.


def test_q_finds_an_item_by_title(db: SqliteInventoryDatabase, username: str, box: Box):
    add(db, username, box, "Cordless drill")
    add(db, username, box, "Hammer")

    assert [i.title for i in db.search_items(username, q="drill").entries] == [
        "Cordless drill"
    ]


def test_q_is_case_insensitive(db: SqliteInventoryDatabase, username: str, box: Box):
    add(db, username, box, "Cordless Drill")

    assert db.search_items(username, q="DRILL").total == 1


def test_q_matches_part_of_a_word(db: SqliteInventoryDatabase, username: str, box: Box):
    add(db, username, box, "Cordless drill")

    assert db.search_items(username, q="ordless").total == 1


def test_q_finds_an_item_by_tag(db: SqliteInventoryDatabase, username: str, box: Box):
    add(db, username, box, "Hammer", tags=["tools"])
    add(db, username, box, "Trowel", tags=["garden"])

    assert [i.title for i in db.search_items(username, q="tools").entries] == ["Hammer"]


def test_no_q_returns_everything(db: SqliteInventoryDatabase, username: str, box: Box):
    add(db, username, box, "Drill")
    add(db, username, box, "Hammer")

    assert db.search_items(username).total == 2


def test_tag_filtering_is_conjunctive(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    """An item must carry every tag given, not any of them (§6.3)."""
    add(db, username, box, "Both", tags=["tools", "power"])
    add(db, username, box, "One", tags=["tools"])
    add(db, username, box, "Other", tags=["power"])

    found = db.search_items(username, tags=["tools", "power"])

    assert [i.title for i in found.entries] == ["Both"]


def test_a_tag_filter_is_normalised(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    add(db, username, box, "Hammer", tags=["tools"])

    assert db.search_items(username, tags=["  TOOLS "]).total == 1


def test_a_tag_that_could_never_have_been_stored_is_rejected(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    """
    Not ignored. The filter is conjunctive, so dropping an unstorable tag from
    ["tools", "hand tools"] would widen the search rather than narrow it to nothing.
    """
    add(db, username, box, "Both", tags=["tools"])

    with pytest.raises(ValueError, match=r"\[a-z0-9-\]"):
        db.search_items(username, tags=["tools", "hand tools"])


def test_the_box_filter_restricts_to_one_box(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    cellar = db.create_box(username, NewBox(number=2))
    add(db, username, box, "Drill")
    add(db, username, cellar, "Skis")

    found = db.search_items(username, box_id=cellar.public_id)

    assert [i.title for i in found.entries] == ["Skis"]


def test_the_box_filter_rejects_an_unknown_box(
    db: SqliteInventoryDatabase, username: str
):
    with pytest.raises(BoxNotFoundError):
        db.search_items(username, box_id="nope")


def test_has_image_filters_both_ways(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    """Drives the photo pass, which asks for the items still missing one (§8)."""
    with_image = add(db, username, box, "Drill")
    add(db, username, box, "Hammer")
    set_row(db, with_image, image_key="abc123")

    assert [i.title for i in db.search_items(username, has_image=True).entries] == [
        "Drill"
    ]
    assert [i.title for i in db.search_items(username, has_image=False).entries] == [
        "Hammer"
    ]


def test_filters_compose(db: SqliteInventoryDatabase, username: str, box: Box):
    cellar = db.create_box(username, NewBox(number=2))
    wanted = add(db, username, box, "Cordless drill", tags=["tools", "power"])
    add(db, username, box, "Cordless drill", tags=["tools"])
    add(db, username, cellar, "Cordless drill", tags=["tools", "power"])
    add(db, username, box, "Hammer", tags=["tools", "power"])
    set_row(db, wanted, image_key="abc123")

    found = db.search_items(
        username,
        q="drill",
        tags=["tools", "power"],
        box_id=box.public_id,
        has_image=True,
    )

    assert [i.public_id for i in found.entries] == [wanted.public_id]
    assert found.total == 1


def test_results_come_back_newest_first(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    """
    Server-defined order, today `updated_at` descending. Callers must not re-sort, so
    that the day this becomes relevance ranking the app improves for free (§6.3).
    """
    for n, stamp in enumerate(["2021", "2023", "2022"]):
        item = add(db, username, box, f"Item {n}")
        set_row(db, item, updated_at=f"{stamp}-01-01T00:00:00+00:00")

    assert [i.title for i in db.search_items(username).entries] == [
        "Item 1",
        "Item 2",
        "Item 0",
    ]


def test_search_never_crosses_users(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    other = db.create_user("other", "hash").username
    theirs = db.create_box(other, NewBox(number=1))
    add(db, username, box, "Mine", tags=["tools"])
    add(db, other, theirs, "Theirs", tags=["tools"])

    assert [i.title for i in db.search_items(username).entries] == ["Mine"]
    assert db.search_items(username, q="theirs").total == 0
    assert db.search_items(username, tags=["tools"]).total == 1


# Pagination


def test_total_counts_every_match_not_just_the_page(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    for n in range(10):
        add(db, username, box, f"Item {n}")

    page = db.search_items(username, limit=3)

    assert len(page.entries) == 3
    assert page.total == 10


def test_pagination_walks_a_large_set_exactly_once(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    for n in range(120):
        item = add(db, username, box, f"Item {n:03d}")
        set_row(db, item, updated_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}+00:00")

    seen: list[str] = []
    cursor = None
    while True:
        page = db.search_items(username, limit=25, cursor=cursor)
        assert page.total == 120
        seen.extend(i.title for i in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == [f"Item {n:03d}" for n in reversed(range(120))]


def test_pagination_survives_a_tie_on_updated_at(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    """
    `updated_at` is not unique, so the internal key breaks ties. Without that the
    order is partial and a page boundary can repeat or skip a row.
    """
    for n in range(30):
        item = add(db, username, box, f"Item {n:02d}")
        set_row(db, item, updated_at="2026-01-01T00:00:00+00:00")

    seen: list[str] = []
    cursor = None
    while True:
        page = db.search_items(username, limit=7, cursor=cursor)
        seen.extend(i.title for i in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == [f"Item {n:02d}" for n in range(30)]
    assert len(seen) == 30


def test_a_filter_survives_pagination(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    for n in range(30):
        item = add(db, username, box, f"Item {n:02d}", tags=["keep"] if n % 2 else [])
        set_row(db, item, updated_at=f"2026-01-01T00:00:{n:02d}+00:00")

    seen: list[str] = []
    cursor = None
    while True:
        page = db.search_items(username, tags=["keep"], limit=4, cursor=cursor)
        assert page.total == 15
        seen.extend(i.title for i in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == [f"Item {n:02d}" for n in range(1, 30, 2)]


def test_the_last_page_has_no_cursor(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    for n in range(5):
        add(db, username, box, f"Item {n}")

    page = db.search_items(username, limit=5)

    assert len(page.entries) == 5
    assert page.next_cursor is None


def test_a_bad_cursor_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(InvalidCursorError):
        db.search_items(username, cursor="not-a-cursor")


# Tags, §6.5


def test_tags_are_listed_with_counts_most_used_first(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    add(db, username, box, "Drill", tags=["tools", "power"])
    add(db, username, box, "Hammer", tags=["tools"])
    add(db, username, box, "Saw", tags=["tools"])

    assert [(t.tag, t.count) for t in db.list_tags(username)] == [
        ("tools", 3),
        ("power", 1),
    ]


def test_tags_are_empty_when_nothing_is_tagged(
    db: SqliteInventoryDatabase, username: str, box: Box
):
    add(db, username, box, "Drill")

    assert db.list_tags(username) == []


def test_tags_ignore_other_users(db: SqliteInventoryDatabase, username: str, box: Box):
    other = db.create_user("other", "hash").username
    theirs = db.create_box(other, NewBox(number=1))
    add(db, other, theirs, "Theirs", tags=["secret"])
    add(db, username, box, "Mine", tags=["tools"])

    assert [t.tag for t in db.list_tags(username)] == ["tools"]
