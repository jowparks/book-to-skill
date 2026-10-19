# PDF extraction bake-off: scanned technical book

Status: **DONE — evidence for SKILL.md Step 1.6 (marker with forced OCR, then Sonnet proofreading)**

Date: 2026-10-18. Machine: Apple Silicon Mac, CPU/MPS only; jobs overlapped, so times are rough.

## Question

Which PDF-to-Markdown path gives book-to-skill usable input for a scanned technical book with dense
equations, matrices and tables?

## Setup

- Source: a scanned, image-only PDF of a power-electronics textbook (Erickson & Maksimović, 2nd ed.). Its only
  text layer is a per-page watermark. Not committed (copyrighted).
- Bench: 12 pages — 8 consecutive Ch. 2 pages (prose + 20 numbered equations), 3 Ch. 7 state-space pages
  (matrix equations), 1 Ch. 8 page (transfer functions + a 3×5 table).
- Ground truth: 40 numbered equations and the 15 table cells, transcribed by hand from the scans.
- Equation grading: Claude subagents compared each candidate's equation against the reference —
  exact / minor (one small symbol error) / wrong / missing. Spot-checked by hand against the scans.
- Prose: share of reference word bigrams (maths stripped) found in the candidate, over three prose-heavy pages.

## Results

| Method | Equations exact /40 | Table /15 | Prose | Time, 12 pages |
|---|---|---|---|---|
| marker `--force_ocr` + Sonnet proofread (edits only) | **40** | **15** | 99.5% | 309 s + ~30 s |
| marker `--force_ocr` + Opus proofread (edits only) | 40 | 15 | 99.5% | 309 s + ~45 s |
| Claude Sonnet transcription, one page per subagent | 39 (1 page refused) | 15 | 99.8% | ~12 s/page |
| OpenAI gpt-6-sol transcription from page images | 37 | 15 | 99.8%¹ | 41 s |
| OpenAI gpt-5.4-mini transcription from page images | 36 | 14 | 99.8% | 8 s |
| marker `--force_ocr` | 31 | 15 | 99.5% | 309 s |
| marker `--force_ocr` + marker LLM pass (gpt-5-mini) | 28 | 15 | 99.5% | 653 s |
| MinerU 4 local, advanced tier | 21 | 15 | 98.8% | 248 s |
| MinerU 4 local, standard tier | 20 | 15 | 98.8% | 123 s |
| marker + LLM pass, no forced OCR | 20 | 15 | 91.5% | — |
| Docling + OCR (ocrmac) + formula enrichment | 2 | 1 | 96.2% | 1,513 s |
| Nougat | 1 | 2 | 82.3% | 316 s |
| ocrmypdf (Tesseract) + pdftotext | 1 | 1 | 97.4% | 19 s |
| macOS Vision OCR | 1 | 0 | 96.1% | 6 s |
| Docling as shipped (`--mode technical`, `do_ocr=False`) | 0 | 0 | 0% | 16 s |

¹ The prose reference was built from this output after line-by-line correction against the scans.

## Findings

1. **Forced OCR is what makes marker work on this scan.** Without it, marker trusts the watermark text layer and
   drops most prose into image blocks (597 vs 2,773 words on 8 pages).
2. **Marker's LLM pass does not help** (28 vs 31 exact) and doubles the time; it needs an API key. It is off.
3. **Proofreading against the page images fixes the residue.** Marker's errors are systematic subscript
   misreads (`V_g`→`V_s`), garbled matrix labels and missing hats. A Sonnet subagent fixed all of them; Opus
   was no better.
4. **Claude subagents must edit, not rewrite.** Whole-chunk transcription (12 pages) was stopped by the output
   content filter for both Opus and Sonnet; one single-page transcription was declined on copyright grounds.
   Small `Edit` replacements were never blocked.
5. **Plain OCR engines cannot do the maths** (Tesseract, Apple Vision, Nougat), and Docling as shipped reads
   nothing from a scanned PDF.

## Limits

One book, 12 pages; graders and proofreaders were both Claude (graded against an independent hand reference);
timings are under CPU contention. Born-digital PDFs were not measured — forced OCR may be slower than needed there.
