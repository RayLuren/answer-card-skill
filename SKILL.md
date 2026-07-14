---
name: answer-card-skill
description: Run Codex-managed directory batches that turn arbitrarily named reference-answer PDFs into blank, validated chemistry answer-card PDFs with isolated visual judgment, auditable artifacts, and one safe task report. Use when Codex is asked to process a PDF directory through this project without persisting or repeating reference-answer content.
---

# Batch answer-card generation

## Product entry

Treat `scripts/batch_pipeline.py` as the product interface. For every directory batch, first read [`references/codex-batch-orchestration.md`](references/codex-batch-orchestration.md) and follow its Codex-specific scheduling contract.

Accept a request such as:

```text
调用 <本地 answer-card-skill 项目目录>，
处理 <输入目录> 下的答案 PDF，
输出到 <输出根目录>。
```

## Safety

- Never persist, repeat, summarize, paraphrase, render, or test against reference-answer content.
- Keep source-page PNG evidence transient and within the assigned job path.
- Persist only approved structural fields and fixed error codes; never persist page text, equations, answer keys, free-form reasons, or visual descriptions.
- Require direct visual inspection capability for AI layout judgment. Fail the paper with `CAPABILITY_UNAVAILABLE` if that capability is absent.
- Never create contact sheets or reconstruct clean prompt visuals from completed answer-key graphics.

## Workflow

1. Run `prepare INPUT OUTPUT_ROOT` once. It creates a new immutable run, answer-free outlines, strict `ai_layout_job.attempt-1.json` jobs, and transient source pages.
2. Schedule one fresh-context visual worker per whole paper with bounded concurrency. Each worker may write only the `allowed_output_path` in its job: `ai_layout.attempt-N.json`.
3. Run `accept-ai-layout` for each completed attempt. Only the main Agent may promote validated output to formal `ai_layout.json`.
4. As soon as one paper reaches `ai_layout_valid`, run `build --paper PAPER_ID`. Serialize local XeLaTeX builds while other visual workers continue.
5. Use `fail-paper` for interrupted, unsafe, or incapable workers. Capacity shortage is a queue condition, not a paper failure.
6. After every paper is `validated` or `failed`, run `report` exactly once. A repeated `report` call returns the existing reports without regenerating them.

The state flow is `prepared → awaiting_ai_layout → ai_layout_running → ai_layout_valid → building → validated`, with `failed` as the terminal failure state. A first recoverable attempt failure returns to `awaiting_ai_layout` with attempt 2.

## Retry and stopping rules

- Retry invalid JSON, schema failure, tool interruption, or transient evidence-read failure exactly once in a new fresh-context worker.
- Do not retry structural conflicts, changed source fingerprints, capability preflight failures, or safety refusals.
- The required per-item `unknown` reinspection occurs inside one worker attempt and does not count as the whole-paper retry.
- Stop at the no-image initial PDF. Report prompt-image requirements and wait for approved prompt-side assets; v1 does not bind images automatically.

## Commands

```powershell
.\.venv\Scripts\python scripts\batch_pipeline.py prepare INPUT OUTPUT_ROOT [--metadata INPUT\answercard-batch.yaml] [--visual-workers N]
.\.venv\Scripts\python scripts\batch_pipeline.py status RUN\batch_manifest.json
.\.venv\Scripts\python scripts\batch_pipeline.py accept-ai-layout RUN\batch_manifest.json PAPER_ID RUN\.work\PAPER_ID\ai_layout.attempt-N.json
.\.venv\Scripts\python scripts\batch_pipeline.py build RUN\batch_manifest.json [--paper PAPER_ID]
.\.venv\Scripts\python scripts\batch_pipeline.py fail-paper RUN\batch_manifest.json PAPER_ID --code CODE
.\.venv\Scripts\python scripts\batch_pipeline.py report RUN\batch_manifest.json
```

Run project tests only through:

```powershell
.\.venv\Scripts\python scripts\run_tests.py
```
