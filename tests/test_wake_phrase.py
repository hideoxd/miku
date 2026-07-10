import pytest

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


# Fuzzy matching: Whisper base.en mangles "Miku" constantly (this was the bug —
# an exact-substring match woke on almost none of these).
@pytest.mark.parametrize(
    "heard",
    ["hi miko", "meeku", "mikko", "hey mikko", "himiku", "heymiku",
     "mee koo", "hi meeko", "nikku", "Hi Miko are you there"],
)
def test_fuzzy_variants_wake(heard):
    assert match_wake_phrase(heard, "miku")[0], f"{heard!r} should wake"


def test_fuzzy_variant_keeps_command():
    woke, rest = match_wake_phrase("miko set a timer for ten minutes", "miku")
    assert woke and rest == "set a timer for ten minutes"


@pytest.mark.parametrize(
    "heard",
    ["hello there", "what time is it", "play some music",
     "turn on the lights", "let's go to the market"],
)
def test_normal_speech_does_not_wake(heard):
    assert not match_wake_phrase(heard, "miku")[0], f"{heard!r} must not wake"
