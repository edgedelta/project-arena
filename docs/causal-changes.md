# Causal change identification

Current bundled scenarios have no controlled, product-accessible introducing history declared, so D6 defaults to `not_applicable`. Repository access alone does not make a case eligible. To enable it, create a healthy revision and a fault-introducing revision in an operator-owned repository, deploy the faulty revision, verify the fault and record the deployed revision. Confirm the tested product can read the repository and relevant history during the run. Have a reviewer check the causal diff and record these facts in the judge-only truth file.

Add `causal_change` inside the truth file's `ground_truth` object:

```json
"causal_change": {
  "eligible": true,
  "repository": "operator-owned repository identifier",
  "introducing_commit": "exact deployed introducing commit",
  "diff": "recorded relevant diff",
  "mechanism": "why this change produces the observed fault",
  "access_evidence": "recorded product/run access check, timestamp and deployed revision receipt",
  "reviewed_by": "reviewer identifier"
}
```

The scorer requires these fields and hashes them with ground truth. It validates their structure, not whether deployment or access really happened; retain the underlying receipts for review. Metadata must describe this product's access in this run. For an ineligible case, use `{"eligible": false, "reason": "explanation"}`. Omission defaults to ineligible. Do not give judge-only truth to the investigated product.

Causal change identification is reported alongside the other metrics in the [comparison tables](../README.md#how-to-compare-results).
