"""The only module that imports the Gemini SDK.

Everything that wants a model call comes through here, which is what makes
these four things possible in one place: a timeout, one retry, a cache, and a
row in llm_calls for every call. If a second module imports google.genai, the
cost tracking and the budget stop being true.

Rules from CLAUDE.md §7 that this module enforces:
  - no personal data in prompts (no names, emails, ids)
  - every call records its prompt id and version
  - Gemini explains; it never grades, picks questions or sets levels
  - over budget, callers get a GeminiUnavailable and show the worked solution

Implemented in M9.
"""

from dataclasses import dataclass

TIMEOUT_SECONDS = 20
MAX_RETRIES = 1


class GeminiUnavailable(RuntimeError):
    """Raised when the model fails, times out, or the daily budget is spent.

    Callers must catch this. The quiz never depends on Gemini: the fallback is
    the item's own worked solution plus its textbook page.
    """


@dataclass(frozen=True)
class Prompt:
    """A versioned prompt loaded from app/ai/prompts/.

    The id and version are written to llm_calls so that a change in output
    quality can be traced to the prompt that caused it.
    """

    id: str
    version: str
    text: str


def generate(prompt: Prompt, variables: dict, *, stream: bool = False):
    raise NotImplementedError("M9")


def embed(texts: list[str]) -> list[list[float]]:
    """Embed for RAG. Must return 768 dimensions.

    textbook_chunks.embedding is vector(768); a model that returns another
    width fails at insert time, which is the cheap moment to find out.
    """
    raise NotImplementedError("M9")
