"""
One simple A/B test: do fewer choices help people decide?

    Group A  the assistant answers as normal (often names 4-5 dishes)
    Group B  the assistant names at most 3 dishes, best match first

Idea behind it: with too many options people read the answer and still don't
pick anything. If that is true, group B should order more often.

How people are split:
    Each visitor is put in A or B by their session id, not at random each time.
    So the same person always sees the same version for their whole visit, and
    the split comes out close to 50/50 on its own.

How to read the result:
    python analysis/run.py   ->  "A/B test" section
    It compares the order rate of the two groups and says whether the gap is
    big enough to trust, or could just be luck.

To stop the test, set RUNNING = False. Everyone then gets version A.
"""
import hashlib

NAME    = "fewer_choices"
RUNNING = True

PROMPT_B = (
    "\n\nANSWER LENGTH RULE (overrides the length guidance above): never name more "
    "than 3 dishes in one answer. Put the single best match first. If more dishes "
    "match, say how many others there are and offer to show them."
)


def group_for(session_id: str) -> str:
    """'A' or 'B'. Same session id always gives the same group."""
    if not RUNNING or not session_id:
        return "A"
    digest = hashlib.sha256(f"{NAME}:{session_id}".encode()).hexdigest()
    return "B" if int(digest, 16) % 2 else "A"


def extra_prompt(group: str) -> str:
    """Instruction added to the assistant's prompt for this group."""
    return PROMPT_B if group == "B" else ""
