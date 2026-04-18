---
name: hello-skill
description: A friendly greeter skill that demonstrates a SKILL.md with a references directory.
version: 1.2.0
---

# Hello Skill

When invoked, this skill greets the user with a context-aware salutation.

## Usage

Invoke with the user's name to receive a personalized greeting. See
`references/greetings.md` for the canonical greeting templates.

## Implementation Notes

- Reads templates from references/greetings.md
- Falls back to "Hello" if no template matches
