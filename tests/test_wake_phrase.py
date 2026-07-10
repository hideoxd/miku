from friday.service import match_wake_phrase


def test_plain_wake():
    assert match_wake_phrase("Hi Miku", "miku") == (True, "")


def test_one_shot_command_after_phrase():
    woke, rest = match_wake_phrase("Hi Miku, what's the weather?", "miku")
    assert woke and rest == "what's the weather"


def test_case_insensitive():
    assert match_wake_phrase("HEY MIKU please help", "miku")[0]


def test_no_match():
    assert match_wake_phrase("hello there", "miku") == (False, "")


def test_empty_inputs():
    assert match_wake_phrase("", "miku") == (False, "")
    assert match_wake_phrase("hi miku", "") == (False, "")
