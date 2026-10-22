"""The adaptive engine — plain Python, no AI, fully testable.

This is the part the committee will interrogate, so it stays readable and every
decision it makes records why it made it. It takes plain data in and returns
plain data out: no database calls, no Gemini, no framework. That is what lets
the tests run a synthetic student through 5 sessions in milliseconds.

Policy version: rules-v1.0 — stored on every session so a later policy can be
compared against logged attempts without rewriting history.

Implemented in M7. The constants below are the rules from CLAUDE.md §6,
gathered in one place so the implementation and the tests read from the same
numbers.
"""

from typing import Final

POLICY_VERSION: Final = "rules-v1.0"

# Evidence decay applied once at session start: a = 1 + DECAY * (a - 1).
DECAY: Final = 0.9

# mastery = a / (a + b), shown only once the student has answered MIN_ITEMS.
MIN_ITEMS_FOR_LEVEL: Final = 3
WEAK_BELOW: Final = 0.5
STRONG_AT_OR_ABOVE: Final = 0.8

# A wrong answer in the challenge zone (strong and already at tier 3) counts
# for more than an ordinary miss.
CHALLENGE_ZONE_PENALTY: Final = 1.5

# Staircase: two in a row moves the tier, in either direction.
STAIRCASE_RUN: Final = 2
MIN_TIER: Final = 1
MAX_TIER: Final = 3

# Session 2-5 shape: warm-up, weakest x2, next two weakest, one stretch.
SESSION_SIZE: Final = 6
PRETEST_SIZE: Final = 8
POSTTEST_SIZE: Final = 8

# No repeats from the student's last N sessions on that topic. Templates are
# exempt: their numbers change every time.
NO_REPEAT_SESSIONS: Final = 3

# Stuck: mastery below WEAK_BELOW after this many sessions on one level.
STUCK_AFTER_SESSIONS: Final = 3
