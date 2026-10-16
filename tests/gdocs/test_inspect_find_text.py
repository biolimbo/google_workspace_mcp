"""Tests for locating text ranges with inspect_doc_structure(find_text=...)."""

import json
from unittest.mock import Mock

import pytest

from gdocs import docs_tools
from gdocs.docs_structure import TEXT_MATCH_LIMIT, find_text_ranges


def _unwrap(tool):
    """Unwrap a FunctionTool + decorator chain to the original function."""
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _text_run(start, text):
    end = start + len(text.encode("utf-16-le")) // 2
    return {"startIndex": start, "endIndex": end, "textRun": {"content": text}}


def _paragraph(start, *parts):
    """Paragraph from text strings and (width, None) inline-object placeholders."""
    elements = []
    index = start
    for part in parts:
        if isinstance(part, str):
            run = _text_run(index, part)
            elements.append(run)
            index = run["endIndex"]
        else:
            width = part[0]
            elements.append(
                {
                    "startIndex": index,
                    "endIndex": index + width,
                    "inlineObjectElement": {},
                }
            )
            index += width
    return {"startIndex": start, "endIndex": index, "paragraph": {"elements": elements}}


def _table(start, cell_texts):
    cells = []
    index = start + 2  # table start and row start each take one index
    for text in cell_texts:
        paragraph = _paragraph(index + 1, text)  # cell start takes one index
        cells.append({"content": [paragraph]})
        index = paragraph["endIndex"]
    return {
        "startIndex": start,
        "endIndex": index + 1,
        "table": {"tableRows": [{"tableCells": cells}]},
    }


def _doc(*elements):
    return {"body": {"content": list(elements)}}


def _extract_json(result):
    payload = result.split("\n\n", 1)[1].rsplit("\n\nLink:", 1)[0]
    return json.loads(payload)


# "Intro\n" 1-7, "The quick brown fox.\n" 7-28, table from 28
DOC = _doc(
    _paragraph(1, "Intro\n"),
    _paragraph(7, "The quick brown fox.\n"),
    _table(28, ["Status\n", "Differs / Unknown\n"]),
)


class TestFindTextRanges:
    def test_returns_index_range_and_paragraph_for_a_match(self):
        found = find_text_ranges(DOC, "quick brown")

        assert found["count"] == 1
        assert found["truncated"] is False
        assert found["matches"] == [
            {
                "start_index": 11,
                "end_index": 22,
                "paragraph_start_index": 7,
                "paragraph_end_index": 28,
                "in_table": False,
                "context": "The quick brown fox.",
            }
        ]

    def test_counts_non_bmp_characters_as_two_index_units(self):
        doc = _doc(_paragraph(1, "\U0001f600 go\n"))

        match = find_text_ranges(doc, "go")["matches"][0]

        # The emoji occupies indices 1-3, the space 3-4, "go" 4-6.
        assert (match["start_index"], match["end_index"]) == (4, 6)

    def test_inline_objects_count_by_their_index_span(self):
        doc = _doc(_paragraph(1, "a", (1, None), "b\n"))

        match = find_text_ranges(doc, "b")["matches"][0]

        assert (match["start_index"], match["end_index"]) == (3, 4)

    def test_finds_text_inside_table_cells(self):
        found = find_text_ranges(DOC, "Differs / Unknown")

        cell_paragraph = DOC["body"]["content"][2]["table"]["tableRows"][0][
            "tableCells"
        ][1]["content"][0]
        assert found["count"] == 1
        match = found["matches"][0]
        assert match["in_table"] is True
        assert match["start_index"] == cell_paragraph["startIndex"]
        assert match["end_index"] == match["start_index"] + len("Differs / Unknown")

    def test_reports_every_occurrence_in_document_order(self):
        found = find_text_ranges(DOC, "ro")

        assert found["count"] == 2
        assert [m["start_index"] for m in found["matches"]] == [4, 18]

    def test_context_is_clipped_around_the_match(self):
        doc = _doc(_paragraph(1, "x" * 100 + "needle" + "y" * 100 + "\n"))

        match = find_text_ranges(doc, "needle", context_chars=5)["matches"][0]

        assert match["context"] == "xxxxxneedleyyyyy"

    def test_no_match(self):
        found = find_text_ranges(DOC, "lazy dog")

        assert found == {
            "query": "lazy dog",
            "count": 0,
            "matches": [],
            "truncated": False,
        }

    def test_matches_are_capped_but_count_is_not(self):
        doc = _doc(_paragraph(1, "ab " * (TEXT_MATCH_LIMIT + 5) + "\n"))

        found = find_text_ranges(doc, "ab")

        assert found["count"] == TEXT_MATCH_LIMIT + 5
        assert len(found["matches"]) == TEXT_MATCH_LIMIT
        assert found["truncated"] is True

    def test_does_not_match_across_paragraphs(self):
        found = find_text_ranges(DOC, "Intro\nThe")

        assert found["count"] == 0


class TestInspectDocStructureFindText:
    @staticmethod
    def _service(doc):
        service = Mock()
        service.documents.return_value.get.return_value.execute = Mock(return_value=doc)
        return service

    @pytest.mark.asyncio
    @pytest.mark.parametrize("detailed", [False, True])
    async def test_find_text_adds_matches_in_both_modes(self, detailed):
        result = _extract_json(
            await _unwrap(docs_tools.inspect_doc_structure)(
                service=self._service(DOC),
                user_google_email="user@example.com",
                document_id="doc123",
                detailed=detailed,
                find_text="quick brown",
            )
        )

        assert result["text_matches"]["count"] == 1
        match = result["text_matches"]["matches"][0]
        assert (match["start_index"], match["end_index"]) == (11, 22)
        assert "total_length" in result

    @pytest.mark.asyncio
    async def test_find_text_searches_the_requested_tab(self):
        other = {"content": [_paragraph(1, "Elsewhere\n")]}
        doc = {
            "title": "Tabbed",
            "tabs": [
                {"tabProperties": {"tabId": "t.0"}, "documentTab": {"body": other}},
                {
                    "tabProperties": {"tabId": "t.1"},
                    "documentTab": {"body": DOC["body"]},
                },
            ],
        }

        result = _extract_json(
            await _unwrap(docs_tools.inspect_doc_structure)(
                service=self._service(doc),
                user_google_email="user@example.com",
                document_id="doc123",
                tab_id="t.1",
                find_text="quick brown",
            )
        )

        assert result["text_matches"]["count"] == 1
        assert result["inspected_tab_id"] == "t.1"

    @pytest.mark.asyncio
    async def test_output_is_unchanged_without_find_text(self):
        result = _extract_json(
            await _unwrap(docs_tools.inspect_doc_structure)(
                service=self._service(DOC),
                user_google_email="user@example.com",
                document_id="doc123",
            )
        )

        assert "text_matches" not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize("find_text", ["", "   "])
    async def test_empty_find_text_is_rejected_before_any_api_call(self, find_text):
        service = self._service(DOC)

        result = await _unwrap(docs_tools.inspect_doc_structure)(
            service=service,
            user_google_email="user@example.com",
            document_id="doc123",
            find_text=find_text,
        )

        assert result == "Error: find_text must not be empty."
        service.documents.assert_not_called()
