---
description: Add one entry to "Agent corrections" in DECISIONS.md, in the format of the ones already there
argument-hint: "<what the agent got wrong, and where it was fixed>"
---

Add one entry to the "Agent corrections" section of `DECISIONS.md` for this correction:

$ARGUMENTS

## Rules

- **The owner says what went wrong.** The entry records his correction, not your reading
  of it. If the arguments do not say what the agent did wrong, ask; do not reconstruct it.
- **Every fact is checked before it is written.** A pull request number, a commit, a file, a
  count: look it up (`git log`, `git show`, `gh pr view`) or leave it out. If where it was
  fixed is not known yet, ask.
- Touch nothing else: not the other entries, not "Owner mistakes", which is the owner's own
  section.
- Commit nothing.

## The format

Read the section first, and at least its last five entries. Each one is:

- one bullet, starting with the date of the mistake as `YYYY-MM-DD:` (today's date is
  `date -u +%F` if the mistake is today's);
- what the agent did wrong, in the past tense, concrete: the command, the file, the number,
  the claim that was false;
- then where and how it was fixed: "Fixed in PR #N", "Corrected with `gh pr edit` on
  PR #N", "Retracted in PR #N", "Fixed by an amend before pushing", and, when there is one,
  the rule that has followed since;
- in English, plain and short, wrapped like the entries around it;
- for a mistake that happened more than once, the existing form is `YYYY-MM-DD onwards,
  N times:`.

The entry goes at the end of "Agent corrections", in date order, right before
`## Owner mistakes`.

## When done

Show the entry and the `git diff` of `DECISIONS.md`. If any part of it is not checked, say
which.
