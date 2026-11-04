from seh.ownership import ThreeWayDiff, render_three_way


def test_render_contains_user_change_and_proposed_change() -> None:
    diff = ThreeWayDiff(
        path="a.md", base=b"line\n", current=b"line\nuser added\n", proposed=b"line\nseh added\n"
    )

    text = render_three_way(diff)

    assert "+user added" in text
    assert "-user added" in text
    assert "+seh added" in text


def test_render_handles_missing_sides() -> None:
    diff = ThreeWayDiff(path="a.md", base=None, current=None, proposed=b"new\n")

    text = render_three_way(diff)

    assert "+new" in text
