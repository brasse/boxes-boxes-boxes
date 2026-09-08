"""The box half of the storage layer (§6.2, §7.4)."""

import pytest

from boxes3.db.interface import (
    BoxNotEmptyError,
    BoxNotFoundError,
    BoxNumberTakenError,
    InvalidCursorError,
    UsernameTakenError,
    UserNotFoundError,
)
from boxes3.db.schema import item_tags, items
from boxes3.db.sqlite import SqliteInventoryDatabase
from boxes3.ids import ALPHABET
from boxes3.models import BoxUpdate, NewBox, NewItem

# Users


def test_a_user_round_trips(db: SqliteInventoryDatabase):
    created = db.create_user("brasse", "hash")

    assert db.get_user("brasse") == created


def test_a_duplicate_username_is_rejected(db: SqliteInventoryDatabase):
    db.create_user("brasse", "hash")

    with pytest.raises(UsernameTakenError):
        db.create_user("brasse", "other")


def test_an_unknown_user_raises(db: SqliteInventoryDatabase):
    with pytest.raises(UserNotFoundError):
        db.get_user("nobody")


def test_setting_a_password_replaces_the_hash(db: SqliteInventoryDatabase):
    created = db.create_user("brasse", "old")

    updated = db.set_password("brasse", "new")

    assert updated.id == created.id
    assert db.get_user("brasse").password_hash == "new"


def test_setting_a_password_for_an_unknown_user_raises(db: SqliteInventoryDatabase):
    with pytest.raises(UserNotFoundError):
        db.set_password("nobody", "new")


# Creating and reading boxes


def test_a_box_round_trips(db: SqliteInventoryDatabase, username: str):
    created = db.create_box(username, NewBox(number=7, name="Winter", location="Attic"))

    fetched = db.get_box(username, created.public_id)
    assert fetched.number == 7
    assert fetched.name == "Winter"
    assert fetched.location == "Attic"
    assert fetched.item_count == 0


def test_public_ids_are_base62_and_sixteen_characters(
    db: SqliteInventoryDatabase, username: str
):
    box = db.create_box(username, NewBox(number=1))

    assert len(box.public_id) == 16
    assert set(box.public_id) <= set(ALPHABET)


def test_public_ids_differ(db: SqliteInventoryDatabase, username: str):
    ids = {db.create_box(username, NewBox(number=n)).public_id for n in range(1, 21)}

    assert len(ids) == 20


def test_one_user_may_not_reuse_a_box_number(
    db: SqliteInventoryDatabase, username: str
):
    db.create_box(username, NewBox(number=7))

    with pytest.raises(BoxNumberTakenError):
        db.create_box(username, NewBox(number=7))


def test_two_users_may_each_own_a_box_seven(db: SqliteInventoryDatabase, username: str):
    other = db.create_user("other", "hash").username

    db.create_box(username, NewBox(number=7))
    db.create_box(other, NewBox(number=7))

    assert db.list_boxes(username).total == 1
    assert db.list_boxes(other).total == 1


def test_a_box_belonging_to_another_user_is_not_found(
    db: SqliteInventoryDatabase, username: str
):
    other = db.create_user("other", "hash").username
    theirs = db.create_box(other, NewBox(number=1))

    with pytest.raises(BoxNotFoundError):
        db.get_box(username, theirs.public_id)


def test_an_unknown_box_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(BoxNotFoundError):
        db.get_box(username, "nope")


def test_item_count_is_derived(db: SqliteInventoryDatabase, username: str):
    box = db.create_box(username, NewBox(number=1))
    db.create_item(username, NewItem(title="drill", box_id=box.public_id))
    db.create_item(username, NewItem(title="saw", box_id=box.public_id))

    assert db.get_box(username, box.public_id).item_count == 2


# Listing, searching, ordering, pagination


def test_boxes_come_back_in_number_order(db: SqliteInventoryDatabase, username: str):
    for number in (5, 1, 3):
        db.create_box(username, NewBox(number=number))

    page = db.list_boxes(username)

    assert [box.number for box in page.entries] == [1, 3, 5]


def test_q_matches_the_box_number(db: SqliteInventoryDatabase, username: str):
    db.create_box(username, NewBox(number=12))
    db.create_box(username, NewBox(number=99))

    page = db.list_boxes(username, q="12")

    assert [box.number for box in page.entries] == [12]


def test_q_matches_the_name_case_insensitively(
    db: SqliteInventoryDatabase, username: str
):
    db.create_box(username, NewBox(number=1, name="Winter clothes"))
    db.create_box(username, NewBox(number=2, name="Tools"))

    page = db.list_boxes(username, q="WINTER")

    assert [box.number for box in page.entries] == [1]


def test_q_matches_the_location(db: SqliteInventoryDatabase, username: str):
    db.create_box(username, NewBox(number=1, location="Basement"))
    db.create_box(username, NewBox(number=2, location="Attic"))

    page = db.list_boxes(username, q="base")

    assert [box.number for box in page.entries] == [1]


def test_total_counts_every_match_not_just_the_page(
    db: SqliteInventoryDatabase, username: str
):
    for number in range(1, 11):
        db.create_box(username, NewBox(number=number))

    page = db.list_boxes(username, limit=3)

    assert len(page.entries) == 3
    assert page.total == 10


def test_pagination_walks_a_large_set_exactly_once(
    db: SqliteInventoryDatabase, username: str
):
    for number in range(1, 121):
        db.create_box(username, NewBox(number=number))

    seen: list[int] = []
    cursor = None
    while True:
        page = db.list_boxes(username, limit=25, cursor=cursor)
        seen.extend(box.number for box in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == list(range(1, 121))


def test_the_last_page_has_no_cursor(db: SqliteInventoryDatabase, username: str):
    for number in range(1, 6):
        db.create_box(username, NewBox(number=number))

    page = db.list_boxes(username, limit=5)

    assert len(page.entries) == 5
    assert page.next_cursor is None


def test_a_search_survives_pagination(db: SqliteInventoryDatabase, username: str):
    for number in range(1, 31):
        location = "Attic" if number % 2 else "Cellar"
        db.create_box(username, NewBox(number=number, location=location))

    seen: list[int] = []
    cursor = None
    while True:
        page = db.list_boxes(username, q="attic", limit=4, cursor=cursor)
        assert page.total == 15
        seen.extend(box.number for box in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == list(range(1, 31, 2))


def test_a_bad_cursor_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(InvalidCursorError):
        db.list_boxes(username, cursor="not-a-cursor")


# Updating


def test_an_omitted_field_is_left_alone(db: SqliteInventoryDatabase, username: str):
    box = db.create_box(username, NewBox(number=1, name="Winter", location="Attic"))

    updated = db.update_box(username, box.public_id, BoxUpdate(name="Summer"))

    assert updated.name == "Summer"
    assert updated.location == "Attic"


def test_an_explicit_null_clears_a_field(db: SqliteInventoryDatabase, username: str):
    box = db.create_box(username, NewBox(number=1, name="Winter", location="Attic"))

    updated = db.update_box(username, box.public_id, BoxUpdate(location=None))

    assert updated.location is None
    assert updated.name == "Winter"


def test_an_empty_update_changes_nothing(db: SqliteInventoryDatabase, username: str):
    box = db.create_box(username, NewBox(number=1, name="Winter"))

    assert db.update_box(username, box.public_id, BoxUpdate()) == box


def test_renumbering_onto_a_taken_number_raises(
    db: SqliteInventoryDatabase, username: str
):
    db.create_box(username, NewBox(number=1))
    second = db.create_box(username, NewBox(number=2))

    with pytest.raises(BoxNumberTakenError):
        db.update_box(username, second.public_id, BoxUpdate(number=1))


def test_updating_an_unknown_box_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(BoxNotFoundError):
        db.update_box(username, "nope", BoxUpdate(name="x"))


def test_an_update_keeps_the_item_count(db: SqliteInventoryDatabase, username: str):
    box = db.create_box(username, NewBox(number=1))
    db.create_item(username, NewItem(title="drill", box_id=box.public_id))

    updated = db.update_box(username, box.public_id, BoxUpdate(name="Tools"))

    assert updated.item_count == 1


# Deleting


def test_an_empty_box_deletes(db: SqliteInventoryDatabase, username: str):
    box = db.create_box(username, NewBox(number=1))

    db.delete_box(username, box.public_id)

    with pytest.raises(BoxNotFoundError):
        db.get_box(username, box.public_id)


def test_deleting_a_box_with_items_raises(db: SqliteInventoryDatabase, username: str):
    box = db.create_box(username, NewBox(number=1))
    db.create_item(username, NewItem(title="drill", box_id=box.public_id))
    db.create_item(username, NewItem(title="saw", box_id=box.public_id))

    with pytest.raises(BoxNotEmptyError) as raised:
        db.delete_box(username, box.public_id)

    assert raised.value.item_count == 2
    assert db.get_box(username, box.public_id).item_count == 2


def test_a_forced_delete_takes_the_items_and_their_tags(
    db: SqliteInventoryDatabase, username: str
):
    box = db.create_box(username, NewBox(number=1))
    db.create_item(
        username, NewItem(title="drill", box_id=box.public_id, tags=["tools"])
    )

    db.delete_box(username, box.public_id, force=True)

    with db.engine.connect() as connection:
        assert connection.execute(items.select()).all() == []
        assert connection.execute(item_tags.select()).all() == []


def test_a_forced_delete_leaves_other_boxes_alone(
    db: SqliteInventoryDatabase, username: str
):
    doomed = db.create_box(username, NewBox(number=1))
    keeper = db.create_box(username, NewBox(number=2))
    db.create_item(username, NewItem(title="drill", box_id=doomed.public_id))
    db.create_item(username, NewItem(title="saw", box_id=keeper.public_id))

    db.delete_box(username, doomed.public_id, force=True)

    assert db.get_box(username, keeper.public_id).item_count == 1


def test_deleting_an_unknown_box_raises(db: SqliteInventoryDatabase, username: str):
    with pytest.raises(BoxNotFoundError):
        db.delete_box(username, "nope")


# next-number and locations


def test_the_next_number_starts_at_one(db: SqliteInventoryDatabase, username: str):
    assert db.next_box_number(username) == 1


def test_the_next_number_follows_a_dense_run(
    db: SqliteInventoryDatabase, username: str
):
    for number in (1, 2, 3):
        db.create_box(username, NewBox(number=number))

    assert db.next_box_number(username) == 4


def test_the_next_number_fills_the_first_gap(
    db: SqliteInventoryDatabase, username: str
):
    for number in (1, 2, 4, 5):
        db.create_box(username, NewBox(number=number))

    assert db.next_box_number(username) == 3


def test_the_next_number_is_one_when_one_is_free(
    db: SqliteInventoryDatabase, username: str
):
    for number in (2, 3):
        db.create_box(username, NewBox(number=number))

    assert db.next_box_number(username) == 1


def test_the_next_number_ignores_other_users(
    db: SqliteInventoryDatabase, username: str
):
    other = db.create_user("other", "hash").username
    db.create_box(other, NewBox(number=1))

    assert db.next_box_number(username) == 1


def test_locations_are_distinct_and_sorted(db: SqliteInventoryDatabase, username: str):
    db.create_box(username, NewBox(number=1, location="Attic"))
    db.create_box(username, NewBox(number=2, location="Basement"))
    db.create_box(username, NewBox(number=3, location="Attic"))

    assert db.box_locations(username) == ["Attic", "Basement"]


def test_locations_skip_empty_and_missing_ones(
    db: SqliteInventoryDatabase, username: str
):
    db.create_box(username, NewBox(number=1, location="Attic"))
    db.create_box(username, NewBox(number=2))
    db.create_box(username, NewBox(number=3, location="   "))

    assert db.box_locations(username) == ["Attic"]


def test_locations_ignore_other_users(db: SqliteInventoryDatabase, username: str):
    other = db.create_user("other", "hash").username
    db.create_box(other, NewBox(number=1, location="Their attic"))

    assert db.box_locations(username) == []
