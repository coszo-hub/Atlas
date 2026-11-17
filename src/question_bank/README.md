# Ask Atlas question bank

Questions for building and testing the knowledge graph, each tagged with the question type (the graph relation it
tests) and with its gold answer where it has one.

| # | Type | Question | Gold from |
|---|------|----------|-----------|
| 1 | literature | answered from papers, citing them | paper facts (literature evals) |
| 2 | paper_sensor | which papers used / mention this sensor | reading the papers (to come) |
| 3 | paper_method | methods a paper applies | method vocabulary + reading (to come) |
| 4 | paper_concept | concepts or features a paper studies | concept vocabulary + reading (to come) |
| 5 | site_papers | papers about a site | reading (to come) |
| 6 | site_sensors | sensors at a site | instrument inventory, map sites |
| 7 | sensor_info | make, model, serial, depth of a sensor | OOI asset management |
| 8 | method_sensor | methods applied to a sensor's data | from 2 and 3 (to come) |
| 9 | method_papers | papers that did a method at the RCA | from 3 (to come) |
| 10 | paper_summary | about Author et al. (year) | paper metadata and abstract (to come) |
| 11 | data_availability | date range of a sensor's data, channels | asset-management deployments, StationXML epochs |
| 12 | changes | swaps, deployments, serials over time | asset-management deployments |
| 13 | errors | orientation issues | StationXML azimuths |
| 14 | calibration | calibration dates | asset-management calibrations; the SCPR's control log (scpr_calibrations.py) |
| 0 | other | live status, earthquake counts, QA/QC, Chronfix, figures, tools, background | the existing evals |

## Files

- `question_bank.jsonl`: questions already asked (past sessions, commit messages) and the existing evals'
  (`build_question_bank.py`). All seen, so all **train**.
- `generated_train.jsonl` and `blind/generated_blind.jsonl`: new questions with gold computed from the sources
  (`generate_source_questions.py`), as of the date in each row's `as_of`.

## Train and blind

New questions are split by **entity** (a sensor, a site), not by question: every question about one entity is in the
same half, so tuning on a train question about a sensor cannot leak into a blind one. Entities are grouped by area and
alternated by a hash with a fixed seed, so both halves cover every area. Development uses train only; the blind half
is run once, at the end, and its scores are reported as they come.

## Definitions the gold records both ways (to be settled)

- Orientation issue: components that disagree (`components_disagree`), or a sensor not turned to north (`not_north`).
- Last calibrated: the calibration in force for the latest deployment, and the latest on file.
- Date range of data: from the first deployment to the last deployment's end (or ongoing); gaps within it are not counted.
