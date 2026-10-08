"""The drift tokenizer keeps combining marks and normalizes to NFC (#314).

`_tokens` matched `[^\\W_]+`, i.e. `str.isalnum()` runs, which excludes Unicode
combining marks. Measured on `main`:

    _tokens(NFD("café"))      -> ['cafe']              (same as the bare ASCII word)
    _tokens("नमस्ते दुनिया")     -> ['नमस', 'त', 'द', 'न', 'य']
    _tokens("مَرْحَبًا")          -> five single letters
    cosine(NFC, NFD of "café au lait") = 0.667

and `compute_drift(gold, [NFD(s) for s in gold])` on 40 accented sentences gave
embedding 0.150, `drifted`, for text that renders character-for-character the
same as the golden set.
"""

from __future__ import annotations

import unicodedata

import pytest

from eval_harness.drift import _tokens, compute_drift, hash_embed


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_nfd_and_nfc_tokenize_and_embed_identically() -> None:
    nfc = "café au lait, crème brûlée"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    assert _tokens(nfd) == _tokens(nfc) == ["café", "au", "lait", "crème", "brûlée"]
    assert _cos(hash_embed(nfc), hash_embed(nfd)) == pytest.approx(1.0)


def test_an_accented_word_is_not_its_unaccented_neighbour() -> None:
    assert _tokens(unicodedata.normalize("NFD", "café")) != _tokens("cafe")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("नमस्ते दुनिया", ["नमस्ते", "दुनिया"]),
        ("مَرْحَبًا بِكُم", ["مَرْحَبًا", "بِكُم"]),
        ("שָׁלוֹם", ["שָׁלוֹם"]),
    ],
)
def test_words_with_vowel_marks_stay_whole(text: str, expected: list[str]) -> None:
    assert _tokens(text) == expected


def test_ascii_tokenization_is_unchanged() -> None:
    # The underscore is still a separator, as #108 kept it.
    assert _tokens("Foo_bar BAZ-9 qux!") == ["foo", "bar", "baz", "9", "qux"]


def test_an_nfd_copy_of_the_golden_set_does_not_drift() -> None:
    words = ["café", "naïve", "résumé", "crème", "brûlée", "façade", "jalapeño", "über"]
    gold = [f"{words[i % 8]} {words[(i * 3) % 8]} order {i}" for i in range(40)]
    report = compute_drift(gold, [unicodedata.normalize("NFD", s) for s in gold])
    assert report.embedding.status == "ok"
    assert report.embedding.drift_score == pytest.approx(0.0, abs=1e-9)
