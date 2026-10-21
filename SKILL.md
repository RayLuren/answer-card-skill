---
name: answer-card-skill
description: Generate blank answer-card PDFs through one whole-paper visual AI result and deterministic rendering.
---

# Answer Card Skill v0.5.0

Use the complete repository source tree, resolve its root from this skill, and run project commands there. The whole-paper visual AI is the sole authority for printed structure, scores, percentages, answer blocks, layout, and visual requirements.

## First use and capability preflight

Before processing reference-answer PDFs, follow [docs/getting-started.md](docs/getting-started.md) in this order:

1. Verify access to the repository and input files, permission to write the intended output and temporary directories, and command execution. Verify actual direct inspection of full-page images and the ability to give one whole paper to a visual worker in an independent context; a model name alone does not prove either capability. If a required capability is unavailable, stop with `CAPABILITY_UNAVAILABLE` and identify it.
2. Check Python 3.11+, create or reuse the project's virtual environment, and install the Python dependencies with `python -m pip install -e .`. Keep their declaration in `pyproject.toml`.
3. Reuse an available XeLaTeX installation. On Windows, use official MiKTeX when TeX is missing; on other systems, choose an appropriate official TeX Live or MiKTeX installation. Use its package manager to prepare `ctex`, `xeCJK`, `fontspec`, and the other template packages before the sample build.
4. Check the template's font choices in order: Chinese `SimSun` → `Songti SC` → `Source Han Serif SC` → `Noto Serif CJK SC`; Latin `Times New Roman` → `TeX Gyre Termes`. If either list has no available font, report the missing family and point to the official open-font download in the getting-started guide. Do not bundle fonts or copy Windows font files into a public repository.
5. Build the existing answer-free sample in a new build subdirectory, render every resulting PDF page, and inspect the images. Check Chinese characters, Latin text, bold/italic styles, page numbers, and layout, especially after a font substitution. Passing unit tests alone does not establish TeX or font readiness.

This workflow has no cross-platform automatic installer. Repeat the relevant checks when the runtime, TeX installation, fonts, or host capabilities change.

## Hard safety rules

- Never persist or repeat answers, solutions, reasoning, equation bodies, chemical structures, source-page excerpts, keywords, evidence descriptions, or free notes.
- Never run PDF text extraction, OCR, regex question detection, outline generation, or skeleton generation.
- Never reconstruct a prompt visual from a completed answer-key image.
- A text-only model must stop with `CAPABILITY_UNAVAILABLE` before visual judgment.

## Batch workflow

1. Run `prepare INPUT OUTPUT_ROOT`. It fingerprints first-level PDFs and renders every page at 180 DPI. No text, OCR, outline, or number candidates are produced.
2. Schedule one fresh-context visual worker per whole paper with bounded concurrency. The worker reads `prompts/ai_paper_visual_extract.md`, every ordered page image, and an optional fixed confirmation file. It may write only `allowed_output_path`.
3. Run `accept-ai-paper`. Invalid JSON, schema failure, missing output, or interruption gets one fresh-context retry.
4. `needs_human_review` does not count as the whole-paper retry. Give the user the fixed review request, then run `confirm-ai-paper`. A new immutable revision and a new fresh-context whole-paper job are created; scripts never patch confirmed values into a buildable result.
5. Run serial `build --paper PAPER_ID` as soon as a paper reaches `ai_paper_valid`. Other visual workers may continue within bounded concurrency.
6. After every paper is `validated` or `failed`, run `report` exactly once.

State flow:

`prepared → awaiting_ai_paper → ai_paper_running → ai_paper_valid → building → validated`

Human branch:

`ai_paper_running → needs_human_review → awaiting_human_confirmation → awaiting_ai_paper`

`failed` is terminal. Slot shortage means queueing, not paper failure. Builds are always serial.

## Commands

```powershell
python scripts/batch_pipeline.py prepare INPUT OUTPUT_ROOT
python scripts/batch_pipeline.py status RUN\batch_manifest.json
python scripts/batch_pipeline.py accept-ai-paper RUN\batch_manifest.json PAPER_ID ATTEMPT_JSON
python scripts/batch_pipeline.py confirm-ai-paper RUN\batch_manifest.json PAPER_ID CONFIRMATION_JSON
python scripts/batch_pipeline.py build RUN\batch_manifest.json --paper PAPER_ID
python scripts/batch_pipeline.py fail-paper RUN\batch_manifest.json PAPER_ID --code CODE
python scripts/batch_pipeline.py report RUN\batch_manifest.json
```

qspec v2 machine keys are internal. Render `display_id`; bind prompt images by machine `item_id`. Do not reject or rewrite duplicate, discontinuous, or parent/descendant display numbers.

For scheduling, retries, recovery, and worker handoff, read [references/codex-batch-orchestration.md](references/codex-batch-orchestration.md). For exact schemas, read [docs/data-contracts.md](docs/data-contracts.md).

Use `python scripts/run_tests.py` for code verification; keep first-use sample rendering and visual inspection separate from the unit-test result.
