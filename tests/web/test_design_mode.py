"""Tests for Design Mode (UI Annotation)."""

from __future__ import annotations

import pytest

from breadmind.web.design_mode import DesignMode, UIAnnotation


class TestDesignMode:
    def test_activate_deactivate(self):
        dm = DesignMode()
        assert not dm.active
        dm.activate()
        assert dm.active
        dm.deactivate()
        assert not dm.active

    def test_add_annotation_with_selector(self):
        dm = DesignMode()
        ann = dm.add_annotation(selector="#header", text="Make it blue")
        assert isinstance(ann, UIAnnotation)
        assert ann.element_selector == "#header"
        assert ann.annotation_text == "Make it blue"

    def test_add_annotation_with_coordinates(self):
        dm = DesignMode()
        ann = dm.add_annotation(text="Fix alignment", coordinates=(100, 200))
        assert ann.coordinates == (100, 200)

    def test_add_annotation_no_target_raises(self):
        dm = DesignMode()
        with pytest.raises(ValueError, match="selector or coordinates"):
            dm.add_annotation(text="orphan annotation")

    def test_add_annotation_invalid_type_raises(self):
        dm = DesignMode()
        with pytest.raises(ValueError, match="Invalid annotation type"):
            dm.add_annotation(selector=".x", annotation_type="destroy")

    def test_get_annotations_all(self):
        dm = DesignMode()
        dm.add_annotation(selector=".a", text="one")
        dm.add_annotation(selector=".b", text="two", annotation_type="fix")
        assert len(dm.get_annotations()) == 2

    def test_get_annotations_filtered(self):
        dm = DesignMode()
        dm.add_annotation(selector=".a", text="one", annotation_type="comment")
        dm.add_annotation(selector=".b", text="two", annotation_type="fix")
        fixes = dm.get_annotations(annotation_type="fix")
        assert len(fixes) == 1
        assert fixes[0].annotation_text == "two"

    def test_remove_annotation(self):
        dm = DesignMode()
        ann = dm.add_annotation(selector=".x", text="remove me")
        assert dm.remove_annotation(ann.id) is True
        assert len(dm.get_annotations()) == 0

    def test_remove_nonexistent(self):
        dm = DesignMode()
        assert dm.remove_annotation("nope") is False

    def test_clear(self):
        dm = DesignMode()
        dm.add_annotation(selector=".a", text="one")
        dm.add_annotation(selector=".b", text="two")
        dm.clear()
        assert len(dm.get_annotations()) == 0

    def test_generate_prompt_empty(self):
        dm = DesignMode()
        assert "No UI annotations" in dm.generate_prompt()

    def test_generate_prompt_with_annotations(self):
        dm = DesignMode()
        dm.add_annotation(selector="#nav", text="Change color", annotation_type="improve")
        dm.add_annotation(selector=".btn", text="Fix padding", annotation_type="fix")
        prompt = dm.generate_prompt()
        assert "IMPROVE" in prompt
        assert "FIX" in prompt
        assert "#nav" in prompt
        assert ".btn" in prompt
