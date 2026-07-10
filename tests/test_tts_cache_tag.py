from friday.config import Settings
from friday.tts import _cache_tag


def test_miku_tag_includes_model_and_voice():
    s = Settings(miku_model="MODEL_A", miku_base_voice="voiceX")
    tag_a = _cache_tag("miku", s)
    assert "MODEL_A" in tag_a and "voiceX" in tag_a
    # Regression: switching the Miku model must change the cache identity,
    # or stale audio from the old voice gets replayed.
    s2 = Settings(miku_model="MODEL_B", miku_base_voice="voiceX")
    assert _cache_tag("miku", s2) != tag_a


def test_other_engines_keyed_on_voice():
    assert _cache_tag("edge", Settings(tts_voice="en-GB-Sonia")) == "edge:en-GB-Sonia"
