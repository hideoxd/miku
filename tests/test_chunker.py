from friday.llm.chunker import SentenceChunker


def feed_all(chunker, text):
    out = []
    for ch in text:  # worst case: token = 1 char
        out.extend(chunker.feed(ch))
    return out


def test_long_sentence_emitted():
    c = SentenceChunker(min_chars=10)
    out = c.feed("This is a decently long sentence. And the rest")
    assert out == ["This is a decently long sentence."]
    assert c.flush() == "And the rest"


def test_short_fragment_merges_with_next_sentence():
    # Regression: "Hi." used to be emitted as its own choppy TTS utterance.
    c = SentenceChunker(min_chars=25)
    out = c.feed("Hi. How are you doing today, friend? More")
    assert out == ["Hi. How are you doing today, friend?"]


def test_short_fragment_waits_when_nothing_follows():
    c = SentenceChunker(min_chars=25)
    assert c.feed("Hi.") == []
    assert c.flush() == "Hi."


def test_abbreviation_not_split():
    c = SentenceChunker(min_chars=5)
    out = c.feed("Talk to Dr. Smith about the plan tomorrow. Done")
    assert out == ["Talk to Dr. Smith about the plan tomorrow."]


def test_decimal_not_split():
    c = SentenceChunker(min_chars=5)
    out = c.feed("The value is 3.14 which is pi, roughly. Next")
    assert out == ["The value is 3.14 which is pi, roughly."]


def test_streaming_char_by_char():
    c = SentenceChunker(min_chars=10)
    out = feed_all(c, "First sentence is here. Second sentence is also here. Tail")
    assert out == ["First sentence is here.", "Second sentence is also here."]
    assert c.flush() == "Tail"
