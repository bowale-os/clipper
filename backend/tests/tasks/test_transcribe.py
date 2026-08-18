import pytest

from app.tasks.transcribe import _as_dicts


class _Model:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


def test_as_dicts_none():
    assert _as_dicts(None) == []


def test_as_dicts_empty_list():
    assert _as_dicts([]) == []


def test_as_dicts_plain_dicts_unchanged():
    items = [{"word": "hi"}, {"word": "there"}]
    assert _as_dicts(items) == items


def test_as_dicts_model_objects_converted():
    items = [_Model({"word": "hi"}), _Model({"word": "there"})]
    assert _as_dicts(items) == [{"word": "hi"}, {"word": "there"}]


def test_as_dicts_mixed_list():
    items = [{"word": "hi"}, _Model({"word": "there"})]
    assert _as_dicts(items) == [{"word": "hi"}, {"word": "there"}]


def test_as_dicts_invalid_item_raises_attribute_error():
    # Documents the current failure mode: an item that is neither a dict nor exposes
    # model_dump() isn't guarded against, it just raises.
    with pytest.raises(AttributeError):
        _as_dicts([object()])
