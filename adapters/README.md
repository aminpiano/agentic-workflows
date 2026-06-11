# Adapters

The protocols are vendor-neutral. Adapters describe how to run them with common agent environments.

## Generic Agent

Any agent can use the protocols if it can:

- read files
- write files
- run small scripts
- keep long outputs in files instead of chat

## Claude

Claude-style agents work well for:

- long-form planning
- review and critique
- maintaining project instructions
- running worker agents when the host supports subagents

Use a project instruction file to point Claude at the protocol entry point and the current run folder.

## Codex

Codex-style coding agents work well for:

- repository inspection
- script edits
- schedule generation
- deterministic verification
- Git and GitHub publishing workflows

Use explicit run folders and avoid asking the main session to read raw source corpora.

## Gemini

Gemini-style agents can be used as independent reviewers, critics, or bottom-of-schedule workers.

They are most useful when you want a different model family to attack blind spots in a plan or research map.

## Rule Of Thumb

Use the filesystem as the shared state. Use the model as a worker. Do not use chat history as the database.
