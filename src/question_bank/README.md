# Ask Atlas question bank

Questions for building and testing the knowledge graph, each tagged with the question type (the graph relation it
tests) and with its gold answer where it has one.

| # | Type | Question | Gold from |
|---|------|----------|-----------|
| 1 | literature | answered from papers, citing them | paper facts: the literature evals, and authored/ (read from each paper) |
| 2 | paper_sensor | which papers used / mention this sensor | read from each candidate paper, authored/sensor_papers.json |
| 3 | paper_method | methods a paper applies | method vocabulary + reading, authored/paper_topics.json |
| 4 | paper_concept | concepts or features a paper studies; the papers on a concept | concept vocabulary + reading, authored/paper_topics.json |
| 5 | site_papers | papers about a site | each paper's study area, authored/paper_topics.json |
| 6 | site_sensors | sensors at a site | instrument inventory, map sites |
| 7 | sensor_info | make, model, serial, depth of a sensor | OOI asset management |
| 8 | method_sensor | methods applied to a sensor's data | from 2 and 3 |
| 9 | method_papers | papers that did a method with RCA data | from 3 and each paper's RCA use |
| 10 | paper_summary | about Author et al. (year) | the paper's key points, authored/ (read from its abstract) |
| 11 | data_availability | date range of a sensor's data, channels | asset-management deployments, StationXML epochs |
| 12 | changes | swaps, deployments, serials over time | asset-management deployments |
| 13 | errors | orientation issues | StationXML azimuths |
| 14 | calibration | calibration dates | asset-management calibrations; the SCPR's control log (scpr_calibrations.py) |
| 0 | other | live status, earthquake counts, QA/QC, Chronfix, figures, tools, background | the existing evals |

## Files

- `question_bank.jsonl`: questions already asked (past sessions, commit messages) and the existing evals'
  (`build_question_bank.py`). All seen, so all **train**.
- `literature_train.jsonl` and `blind/literature_blind.jsonl`: literature and paper-summary questions on 75 papers
  across Axial, Hydrate Ridge, the Cascadia margin, acoustics and DAS, vent biology and the Oregon shelf, written from
  each paper's abstract (`authored/literature_batch*.json`, built by `build_literature_questions.py`, which fails if
  any fact's pattern is not in the paper's own abstract or full text). Every answer must cite the paper.
- `links_train.jsonl` and `blind/links_blind.jsonl`: types 2, 3, 4, 5, 8 and 9 (`build_link_questions.py`), from two
  authored files. `authored/sensor_papers.json`: for 38 sensors (the seismometers, pressure instruments, sonars, camera,
  samplers, FETCH, DAS, strainmeter, echosounder and hydrophones), the papers that **used** the sensor's data (analyzed
  its records in their own methods or results, a comparison included) and those that only **mention** it (name or
  describe it, or use only a product others made from it, such as a catalog), judged by reading the passages of every
  candidate `gather_sensor_candidates.py` finds across the corpus (a paper naming the sensor, or its site and kind
  together). `authored/paper_topics.json`: for the 136 papers that used one of them or have literature questions, the
  methods each applies and the concepts it studies (most specific vocabulary entry; a broad question takes in the
  children), whether it analyzes RCA data (or only RCA products such as the earthquake catalog) and its study sites.
  The vocabulary's word matches were shown as hints only. Paper sets for 3, 4, 5 and 9 cover these 136 papers
  (`gold.scope`): a paper outside them is unknown, not wrong.
- `generated_train.jsonl` and `blind/generated_blind.jsonl`: new questions with gold computed from the sources
  (`generate_source_questions.py`), as of the date in each row's `as_of`.

## Train and blind

New questions are split by **entity** (a sensor, a site), not by question: every question about one entity is in the
same half, so tuning on a train question about a sensor cannot leak into a blind one. Entities are grouped by area and
alternated by a hash with a fixed seed, so both halves cover every area. The link questions keep the splits the other
files give a sensor or a paper; a method, a concept and a site's papers are entities of their own. A method's papers
(type 9) can include a paper whose own method question is blind: the leak is one paper-method pair per paper. Development uses train only; the blind half
is run once, at the end, and its scores are reported as they come.

## Definitions the gold records both ways (to be settled)

- Orientation issue: components that disagree (`components_disagree`), or a sensor not turned to north (`not_north`).
- Last calibrated: the calibration in force for the latest deployment, and the latest on file.
- Date range of data: from the first deployment to the last deployment's end (or ongoing); gaps within it are not counted.
