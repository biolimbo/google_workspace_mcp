"""Tests for rendering pending suggestions in the Markdown converter."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gdocs.docs_markdown import SUGGESTION_LEGEND, convert_doc_to_markdown


def _run(text, style=None, **extra):
    run = {"content": text, "textStyle": style or {}}
    run.update(extra)
    return {"textRun": run}


def _doc(*paragraphs):
    return {
        "title": "Suggestions",
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": list(elements),
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    }
                }
                for elements in paragraphs
            ]
        },
    }


SUGGESTED_DOC = _doc(
    [
        _run("The fox jumps over the "),
        _run("sleeping dog", suggestedInsertionIds=["suggest.1"]),
        _run("lazy dog", suggestedDeletionIds=["suggest.1"]),
        _run(".\n"),
    ]
)


class TestSuggestionMarkers:
    def test_insertion_and_deletion_are_marked(self):
        markdown = convert_doc_to_markdown(SUGGESTED_DOC)

        assert "The fox jumps over the {++sleeping dog++}{--lazy dog--}." in markdown

    def test_legend_precedes_a_document_with_suggestions(self):
        markdown = convert_doc_to_markdown(SUGGESTED_DOC)

        assert markdown.startswith(SUGGESTION_LEGEND)

    def test_no_legend_or_markers_without_suggestions(self):
        markdown = convert_doc_to_markdown(_doc([_run("Plain text.\n")]))

        assert markdown.strip() == "Plain text."

    def test_newline_only_suggested_run_renders_nothing(self):
        markdown = convert_doc_to_markdown(
            _doc([_run("End of line"), _run("\n", suggestedInsertionIds=["s"])])
        )

        body = markdown.removeprefix(SUGGESTION_LEGEND)
        assert "{++" not in body
        assert body.strip() == "End of line"

    def test_legend_is_found_inside_tabs(self):
        doc = {
            "title": "Tabbed",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.0", "title": "Tab 1"},
                    "documentTab": SUGGESTED_DOC,
                }
            ],
        }

        markdown = convert_doc_to_markdown(doc)

        assert markdown.startswith(SUGGESTION_LEGEND)
        assert "{--lazy dog--}" in markdown


class TestSuggestedTextStyle:
    def test_suggested_bold_is_rendered(self):
        doc = _doc(
            [
                _run(
                    "sleeping dog",
                    suggestedTextStyleChanges={
                        "suggest.2": {
                            "textStyle": {"bold": True},
                            "textStyleSuggestionState": {"boldSuggested": True},
                        }
                    },
                ),
                _run("\n"),
            ]
        )

        assert "**sleeping dog**" in convert_doc_to_markdown(doc)

    def test_suggested_removal_of_bold_is_rendered(self):
        doc = _doc(
            [
                _run(
                    "quiet dog",
                    {"bold": True},
                    suggestedTextStyleChanges={
                        "suggest.3": {
                            "textStyle": {},
                            "textStyleSuggestionState": {"boldSuggested": True},
                        }
                    },
                ),
                _run("\n"),
            ]
        )

        assert "**" not in convert_doc_to_markdown(doc)

    def test_unflagged_fields_in_a_suggestion_are_ignored(self):
        doc = _doc(
            [
                _run(
                    "dog",
                    suggestedTextStyleChanges={
                        "suggest.4": {
                            "textStyle": {"bold": True, "italic": True},
                            "textStyleSuggestionState": {"italicSuggested": True},
                        }
                    },
                ),
                _run("\n"),
            ]
        )

        markdown = convert_doc_to_markdown(doc)

        assert "*dog*" in markdown
        assert "**dog**" not in markdown

    def test_suggested_style_combines_with_insertion_marker(self):
        doc = _doc(
            [
                _run(
                    "new words",
                    suggestedInsertionIds=["s"],
                    suggestedTextStyleChanges={
                        "s": {
                            "textStyle": {"bold": True},
                            "textStyleSuggestionState": {"boldSuggested": True},
                        }
                    },
                ),
                _run("\n"),
            ]
        )

        assert "{++**new words**++}" in convert_doc_to_markdown(doc)


class TestReviewFollowUps:
    def test_style_only_suggestion_gets_the_legend(self):
        doc = _doc(
            [
                _run(
                    "dog",
                    suggestedTextStyleChanges={
                        "s": {
                            "textStyle": {"bold": True},
                            "textStyleSuggestionState": {"boldSuggested": True},
                        }
                    },
                ),
                _run("\n"),
            ]
        )

        markdown = convert_doc_to_markdown(doc)

        assert markdown.startswith(SUGGESTION_LEGEND)
        assert "**dog**" in markdown

    def test_suggested_link_is_grouped_and_rendered(self):
        change = {
            "s": {
                "textStyle": {"link": {"url": "https://example.com"}},
                "textStyleSuggestionState": {"linkSuggested": True},
            }
        }
        doc = _doc(
            [
                _run("Read "),
                _run("the ", suggestedTextStyleChanges=change),
                _run("docs", {"bold": True}, suggestedTextStyleChanges=change),
                _run(" now.\n"),
            ]
        )

        markdown = convert_doc_to_markdown(doc)

        assert "[the **docs**](https://example.com)" in markdown

    def test_suggested_link_removal_drops_the_link(self):
        doc = _doc(
            [
                _run(
                    "old link",
                    {"link": {"url": "https://old.example"}},
                    suggestedTextStyleChanges={
                        "s": {
                            "textStyle": {},
                            "textStyleSuggestionState": {"linkSuggested": True},
                        }
                    },
                ),
                _run("\n"),
            ]
        )

        markdown = convert_doc_to_markdown(doc)

        assert "old.example" not in markdown
        assert "old link" in markdown

    def test_deleted_person_chip_is_marked(self):
        doc = _doc(
            [
                _run("Ask "),
                {
                    "person": {
                        "personProperties": {"name": "Ana", "email": "ana@example.com"}
                    },
                    "suggestedDeletionIds": ["s"],
                },
                _run(".\n"),
            ]
        )

        markdown = convert_doc_to_markdown(doc)

        assert "Ask {--[Ana](mailto:ana@example.com)--}." in markdown

    def test_inserted_date_chip_is_marked(self):
        doc = _doc(
            [
                _run("Due "),
                {
                    "dateElement": {"dateElementProperties": {"displayText": "Oct 20"}},
                    "suggestedInsertionIds": ["s"],
                },
                _run("\n"),
            ]
        )

        markdown = convert_doc_to_markdown(doc)

        assert "Due {++" in markdown and "Oct 20" in markdown and "++}" in markdown
