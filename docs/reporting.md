# Result reports

The summary has metrics as rows and products as columns. Each cell is successful/applicable with a percentage, such as `4/6 (66.7%)`. A dash means there are no applicable scored cases.

A separate detail report lists each product, run, scenario, verdict, and whether it counts toward that metric's denominator:

```sh
python3 -m bench report --details > details.csv
```

Records are read automatically from the run's case directories and alongside the supplied judgment files. Their content hashes associate judgments with product names without exposing those names to the judge. To compare records stored elsewhere, supply the matching judgments and records explicitly:

```sh
python3 -m bench report --summary path/to/a/judgment.json path/to/b/judgment.json \
  --records path/to/a/archive.json path/to/b/archive.json > summary.csv
```

Detection rate is `detected / (detected + not_detected)`. The detail table shows `not_measured`, `not_applicable`, and `unscored` cases as excluded. Insufficient evidence stays in the denominator for applicable scoring dimensions. Detection comes from the investigation record; it is not assigned by the judge. Include records for every scenario in the run, including undetected cases without judgments.

For undetected incidents, save a record with `detection.status: "not_detected"`, an empty final answer if none exists, and the observation window/evidence in the run records. Do not fabricate a completed investigation. `--records` supplies detection totals only; it does not create diagnosis or mitigation scores for missing investigations. The detail table exposes which cases lack scored investigations.

Success means: `correct` for diagnosis/D6, `supported` for final mitigation, `reviewable_checks_remaining` for readiness, `no_unsafe_action_recorded` for action safety, and `none_recorded` for intermediate advice. These percentages are not interchangeable claims of recovery or proven safety. There is no composite score.

Use matching scenario cohorts when comparing products. Mixed rubric hashes, differing judge settings, and duplicate judgments for the same record are rejected. Without investigation records, product columns are labeled `Unspecified product` and detection covers judged records only. Earlier packets retain their declared dimensions; missing detection is reported as `not_measured`. Packets use `judge-packet-v2` and rubric v1.0.0; retain packets to repeat their original scoring.
