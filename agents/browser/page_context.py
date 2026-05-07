from __future__ import annotations

from dataclasses import dataclass, field
import re


MAIN_CONTENT_SCRIPT = """
() => {
  const maxTextChars = 24000;
  const maxBlocks = 160;
  const selectors = [
    '#mw-content-text .mw-parser-output',
    'article',
    'main',
    '[role="main"]',
    'body'
  ];
  const root = selectors
    .map((selector) => document.querySelector(selector))
    .find(Boolean);

  if (!root) {
    const text = document.body ? document.body.innerText : '';
    return {
      text: text.slice(0, maxTextChars),
      headings: [],
      truncated: text.length > maxTextChars
    };
  }

  const clone = root.cloneNode(true);
  clone.querySelectorAll([
    'script',
    'style',
    'noscript',
    'nav',
    'header',
    'footer',
    'aside',
    'form',
    'figure',
    'sup',
    '.mw-editsection',
    '.mw-empty-elt',
    '.reference',
    '.references',
    '.reflist',
    '.navbox',
    '.infobox',
    '.sidebar',
    '.toc',
    '.hatnote',
    '.metadata',
    '.ambox',
    '.thumb',
    '.gallery',
    '.printfooter'
  ].join(',')).forEach((element) => element.remove());

  const headings = Array.from(clone.querySelectorAll('h1, h2, h3'))
    .map((element) => (element.innerText || '').replace(/\\s+/g, ' ').trim())
    .filter(Boolean)
    .slice(0, 30);

  const blocks = [];
  let sawExtraBlock = false;
  for (const element of clone.querySelectorAll('p, li')) {
    if (blocks.length >= maxBlocks) {
      sawExtraBlock = true;
      break;
    }
    blocks.push(element);
  }

  const textBlocks = blocks
    .map((element) => (element.innerText || '').replace(/\\s+/g, ' ').trim())
    .filter((text) => text.length > 40);
  const rawText = textBlocks.length > 0 ? textBlocks.join('\\n\\n') : (clone.innerText || '');
  const truncated = sawExtraBlock || rawText.length > maxTextChars;
  const text = rawText.slice(0, maxTextChars);

  return { text, headings, truncated };
}
"""


@dataclass(frozen=True)
class PageContext:
    title: str
    url: str
    headings: list[str] = field(default_factory=list)
    text: str = ""


def clean_page_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned: list[str] = []
    previous_blank = False

    for line in lines:
        if not line:
            if cleaned and not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue

        cleaned.append(line)
        previous_blank = False

    return "\n".join(cleaned).strip()


def truncate_words(value: str, max_chars: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    suffix = "..."
    if max_chars <= len(suffix):
        return suffix[:max_chars]

    clip_budget = max_chars - len(suffix)
    clipped = text[:clip_budget].rsplit(" ", 1)[0].strip()
    if not clipped:
        clipped = text[:clip_budget].strip()
    return f"{clipped}{suffix}"


def extractive_summary(
    page_text: str,
    *,
    max_chars: int = 1200,
    max_sentences: int = 5,
) -> str:
    text = clean_page_text(page_text)
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n+", text)
        if paragraph.strip()
    ]
    candidate = " ".join(paragraphs[:4]) if paragraphs else text
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", candidate)
        if sentence.strip()
    ]

    selected: list[str] = []
    for sentence in sentences:
        proposed = " ".join([*selected, sentence]).strip()
        if selected and len(proposed) > max_chars:
            break

        selected.append(sentence)
        if len(selected) >= max_sentences:
            break

    if selected:
        return truncate_words(" ".join(selected), max_chars)

    return truncate_words(candidate, max_chars)


def _source_label(context: PageContext) -> str:
    title = context.title.strip()
    url = context.url.strip()
    if title and url and url not in title:
        return f"{title} ({url})"
    return title or url or "page"


def _normalized_task(task: str) -> str:
    return " ".join(str(task or "").lower().split())


def _wants_headings(task: str) -> bool:
    lowered = _normalized_task(task)
    return any(marker in lowered for marker in ("heading", "section", "sections"))


def _wants_summary(task: str) -> bool:
    lowered = _normalized_task(task)
    return any(
        marker in lowered
        for marker in (
            "summary",
            "summarize",
            "summarise",
            "overview",
            "findings",
            "takeaways",
            "key points",
            "key point",
        )
    )


def format_page_context_response(task: str, context: PageContext) -> str:
    source = _source_label(context)
    headings = [heading.strip() for heading in context.headings if heading.strip()]
    text = clean_page_text(context.text)

    if _wants_summary(task):
        summary = extractive_summary(text)
        if not summary:
            return f"Summary of {source}:\nNo readable page text was found."
        return f"Summary of {source}:\n{summary}"

    if _wants_headings(task):
        if not headings:
            return f"Headings from {source}:\nNo readable headings were found."
        heading_lines = "\n".join(f"- {heading}" for heading in headings[:20])
        return f"Headings from {source}:\n{heading_lines}"

    content = truncate_words(text, 1800)
    if not content:
        return f"Page content from {source}:\nNo readable page text was found."
    return f"Page content from {source}:\n{content}"
