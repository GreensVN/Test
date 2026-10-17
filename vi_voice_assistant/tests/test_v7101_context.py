"""Ngữ cảnh là snapshot có giới hạn; URL/path và dữ liệu chèn không được thay lại."""
import pytest
from nlu_advanced import ContextMemory


def test_zero_capacity_really_disables_memory():
    memory = ContextMemory(max_items=0)
    for target in ("google", "chrome", "youtube"):
        memory.remember({"intent": "open_website", "target": target})
    assert memory.history == []
    assert memory.last_target is None and memory.last_intent is None
    assert memory.resolve("mở nó") == "mở nó"


@pytest.mark.parametrize("value,error", [
    (-1, ValueError), (-10, ValueError), (True, TypeError), (False, TypeError),
    ("2", TypeError), (None, TypeError), (1.5, TypeError),
])
def test_invalid_memory_capacity_has_explicit_error(value, error):
    with pytest.raises(error, match="max_items"):
        ContextMemory(max_items=value)


def test_remember_takes_a_snapshot_instead_of_retaining_caller_dict():
    payload = {"intent": "open_website", "target": "google", "time": {"minutes": 5}}
    memory = ContextMemory(2)
    memory.remember(payload)
    payload["target"] = "injected"
    payload["time"]["minutes"] = 99
    assert memory.last_target == "google"
    assert memory.history[0]["time"]["minutes"] == 5
    memory.history[0]["time"]["minutes"] = 7
    assert payload["time"]["minutes"] == 99


def test_memory_keeps_only_the_requested_number_of_snapshots():
    memory = ContextMemory(2)
    for target in ("a", "b", "c"):
        memory.remember({"intent": "open_app", "target": target})
    assert [row["target"] for row in memory.history] == ["b", "c"]


@pytest.mark.parametrize("target", [
    "https://example.com/no/AbC", "https://example.com/trang-do/no",
    "nó", r"C:\Users\no\Documents\report.txt", "trang đó",
])
def test_replacement_is_inserted_exactly_once_without_being_rescanned(target):
    memory = ContextMemory()
    memory.remember({"target": target})
    assert memory.resolve("mở nó") == "mở " + target
    assert memory.resolve("mở chúng nó") == "mở " + target


@pytest.mark.parametrize("literal", [
    "https://other.com/no/AbC", "www.example.com/no", "no.com",
    "other.com/no?trang=do", r"C:\Users\no\report.txt", "/home/no/report.txt",
])
def test_literal_urls_and_paths_are_not_pronouns(literal):
    memory = ContextMemory()
    memory.remember({"target": "google"})
    assert memory.resolve("mở " + literal) == "mở " + literal
    assert memory.resolve("mở " + literal + " và mở nó") == "mở " + literal + " và mở google"


@pytest.mark.parametrize("text", ["MỞ NÓ", "MỞ CHÚNG NÓ", "MO NO", "MỞ TRANG ĐÓ"])
def test_context_resolves_uppercase_without_lowercasing_target(text):
    memory = ContextMemory()
    memory.remember({"target": "https://example.com/ID?A=X"})
    prefix = text.split()[0]
    assert memory.resolve(text) == prefix + " https://example.com/ID?A=X"


@pytest.mark.parametrize("text,expected", [(None, ""), (123, "123"), (True, "True")])
def test_context_public_resolver_coerces_nonstring_input(text, expected):
    memory = ContextMemory()
    memory.remember({"target": "google"})
    assert memory.resolve(text) == expected


@pytest.mark.parametrize("value", [None, []])
def test_invalid_context_entry_is_rejected_before_mutating_history(value):
    memory = ContextMemory()
    with pytest.raises(TypeError, match="result"):
        memory.remember(value)
    assert memory.history == []
