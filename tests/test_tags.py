"""Tag normalisation (§4)."""

import pytest

from boxes3.tags import MAX_LENGTH, MAX_TAGS, normalise


def test_tags_are_trimmed_and_lowercased():
    assert normalise(["  Tools ", "POWER"]) == ["power", "tools"]


def test_tags_are_deduplicated_after_normalising():
    assert normalise(["Tools", "tools", " TOOLS "]) == ["tools"]


def test_tags_come_back_sorted():
    """
    Storage keeps them in a table with no ordering column, so reading imposes an order
    anyway. Sorting here means a tag list survives a round trip unchanged.
    """
    assert normalise(["winter", "attic", "power-tools"]) == [
        "attic",
        "power-tools",
        "winter",
    ]


def test_blank_tags_are_dropped():
    assert normalise(["tools", "", "   "]) == ["tools"]


def test_no_tags_is_fine():
    assert normalise([]) == []


def test_hyphens_and_digits_are_allowed():
    assert normalise(["power-tools", "box7"]) == ["box7", "power-tools"]


@pytest.mark.parametrize(
    "tag", ["hand tools", "tools!", "verktyg-å", "TOOLS/POWER", "tools_power"]
)
def test_an_illegal_character_is_rejected(tag):
    with pytest.raises(ValueError, match=r"\[a-z0-9-\]"):
        normalise([tag])


def test_a_tag_at_the_length_limit_is_accepted():
    assert normalise(["x" * MAX_LENGTH]) == ["x" * MAX_LENGTH]


def test_an_over_long_tag_is_rejected():
    with pytest.raises(ValueError, match="longer than 32"):
        normalise(["x" * (MAX_LENGTH + 1)])


def test_the_maximum_number_of_tags_is_accepted():
    tags = [f"tag{n}" for n in range(MAX_TAGS)]

    assert len(normalise(tags)) == MAX_TAGS


def test_too_many_tags_are_rejected():
    with pytest.raises(ValueError, match="more than 20"):
        normalise([f"tag{n}" for n in range(MAX_TAGS + 1)])


def test_duplicates_do_not_count_towards_the_limit():
    """Twenty-five entries, twenty distinct, which is within the limit."""
    tags = [f"tag{n}" for n in range(MAX_TAGS)] + [f"TAG{n}" for n in range(5)]

    assert len(normalise(tags)) == MAX_TAGS
