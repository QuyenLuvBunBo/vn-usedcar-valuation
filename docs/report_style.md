# Report style — what goes in the submitted document, and what stays in the repository

Written after the 30/10 submission was returned with one clear note: **the report must not carry
code, repository paths, README text or Markdown internals.** The reader is the teacher, not a
maintainer; the repository is the appendix.

## 1. Allowed in the report

- Numbers, tables and figures, with units (VND, %, rows).
- Sentences that explain what a number *means*, including its limitations.
- A one-line pointer such as "every number is reproducible from the project repository" — no path,
  no command, no file name.
- Definitions a reader needs to interpret a table (e.g. what "clean MAPE" excludes), stated in prose
  or a footnote.

## 2. Not allowed in the report

| Not allowed | Because | Where it belongs |
|---|---|---|
| Code blocks, `python -m …`, shell commands | the reader is not running the project | `docs/*.md`, README |
| File paths (`data/master/…`), JSON keys, config names | they change; the report is frozen | the matching `docs/*.md` |
| Mentions of README, CONTRIBUTING, "the repo says", Markdown headings | internal process, not a result | `docs/week*.md` |
| Tool names that are ours (`tools/model_gate`, `audit_master`, …) | meaningless to the reader and reads as scaffolding | the methodology doc |
| TODO notes, review comments, "see team chat" | unfinished work | issue tracker / commit messages |

## 3. Where traceability goes instead

Every table in the report has **one** source artefact in the repository, and the repository records
which one:

| Report section | Numbers come from |
|---|---|
| data quality | `docs/week2_status.md`, `normalize_report.json` |
| descriptive statistics | `docs/eda_summary.md` + `docs/figures/` |
| features | `docs/features.md`, `docs/features_ablation.md` |
| benchmark | `docs/benchmark.md`, `docs/test_evaluation.md` |
| error analysis | `docs/error_taxonomy.md`, `docs/error_audit_25.md` |
| anomalies | `docs/case_studies.md`, `docs/intervals.md` |
| label cleaning | `docs/label_flags.md`, `docs/label_cleaning.md` |

## 4. Checklist before submitting

- [ ] Search the document for `docs/`, `.py`, `.csv`, `.json`, `python -m`, `git `, `README`,
      `markdown` — every hit is a defect.
- [ ] Every table states its unit and its row count.
- [ ] Every claim that a number is an improvement is quoted on the **fixed** evaluation set, and the
      sentence says which set that is.
- [ ] Limitations appear before the conclusion, not in a footnote.
- [ ] Format, page count, file name and submitter confirmed against the teacher's form.
