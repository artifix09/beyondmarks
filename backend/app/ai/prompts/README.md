Versioned prompt files live here: explain_*.md, chat.md, draft_mcq.md,
double_check.md, transcribe.md. Each carries an id and a version in its front
matter; app/ai/gemini.py writes both to llm_calls on every call.
