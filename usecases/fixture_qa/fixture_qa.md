---
id: fixture_qa
n_reps: 3
temperature: 0.0
invocation:
  shape: single_call
  prompt_template: |
    Answer the question with ONLY a single short factual answer — no explanation,
    no punctuation beyond the answer itself.
    Question: {question}
metrics:
  - name: exact_answer
    mode: deterministic
    comparison: exact
    direction: higher_better
    params:
      normalize: true
  - name: helpfulness
    mode: semantic
    direction: higher_better
judge_prompt: |
  You are scoring short factual answers. You will receive a JSON array of items, each with
  {input_id, question, reference_answer, candidate_answer}. For each item, score
  `helpfulness` on a 0.0–1.0 scale:
    1.0 = correct and clearly stated
    0.5 = partially correct, ambiguous, or padded with extra text
    0.0 = wrong, empty, or refuses
  Return ONLY a JSON array of objects: {"input_id": ..., "helpfulness": <float>,
  "rationale": "<one short sentence>"}. Do not use any tools; do not search the web.
baseline_model: gemini-2.5-flash-lite
---
# Use Case: Fixture QA (fixture_qa)

## Description
A tiny synthetic use case whose only purpose is to prove the eval loop end to end
(measured call → deterministic scoring → semantic judging → aggregation → drift → report)
without depending on any external data or web search. The questions are common-knowledge
facts with unambiguous answers.

## Input → Output contract
Input: `{ "question": <str> }`. Output: a single short factual answer string.

## Dataset
`usecases/fixture_qa/golden.jsonl` — 5 hand-written records with known answers.

## Rubric
- `exact_answer` (deterministic, exact): candidate equals the reference answer
  (case/space-insensitive).
- `helpfulness` (semantic): judged 0–1 as defined in the judge prompt above.
- Plus the default harness metrics: latency_ms, tokens_in, tokens_out, cost.

## Notes
Self-contained: the candidate is called with a plain completion and NO tools — no web search.
