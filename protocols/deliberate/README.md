# Deliberate

Deliberate is a lightweight protocol for multi-model review rounds.

It is for decisions where one model may overfit the user's preference, miss a tradeoff, or converge too early.

## When To Use

Use it for:

- architecture choices
- protocol design
- naming and packaging decisions
- plan review
- risk review
- "is this idea actually coherent?" checks

Do not use it for obvious implementation tasks.

## Basic Loop

```text
main agent compresses context
  -> asks model A
  -> asks model B
  -> compares agreements and disagreements
  -> asks one follow-up round if needed
  -> writes a decision memo
```

## Round Prompt Shape

```text
Context:
- What is being decided
- What is already known
- Constraints
- Rejected options, if any

Questions:
1. What is the strongest recommendation?
2. What could fail?
3. What option is underrated?
4. What should be decided by the user instead of the model?
```

## Termination

Stop when:

- the answers converge
- the remaining issue is a value judgment
- the next round would repeat prior arguments
- the max round limit is reached

## Output

Write a short decision memo:

```text
Decision:
Rationale:
Rejected options:
Open questions:
Follow-up work:
Model disagreement notes:
```

## Adapter Notes

Deliberate can be run manually by copying prompts between models, or automated with local CLIs. Keep automation thin. The useful part is the compression, disagreement tracking, and stopping rule.
