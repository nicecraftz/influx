# Converted documents are never chunked or embedded; retrieval only sees HTML pages

**Priority: low**

## Problem

`convert` fills `Document.text`, but `embed_pages` (`ingestion/application/page_service.py`) and
`search_passages` (`retrieval/application/search_service.py:41-47`) only know `Page`.
`ContentChunk.page_id` is `NOT NULL`, so a document chunk cannot even be stored. For a university site,
PDFs (calls, regulations, timetables) are most of the useful content, so the chatbot answers "the
passages do not contain this" for exactly the questions people ask. The README states the limitation.

## Approach

1. Schema: make `ContentChunk` reference either source — `page_id` nullable + `document_id` nullable with
   a CHECK that exactly one is set — or introduce a `Source` abstraction (`source_type`, `source_id`,
   `url`, `title`) that both tables feed. Needs a migration (`ISSUE_NO_MIGRATIONS_CREATE_ALL_ONLY.md`).
2. `embed_documents(org)` mirroring `embed_pages`: chunk `Document.text` (Markdown → keep headings as
   context), skip when `text_hash == source_hash`.
3. `search_passages`: `UNION` or a left join on both sources; `Passage.url/title` from the document
   (title = first Markdown heading or file name).
4. Consider larger chunks/overlap for long documents and a `document`/`page` boost in ranking.
