# Product and judge integration

## Investigation records

The `archive` command saves an investigation record; the command name, `archive.json` filename, and `archive-v1` format are retained. Records can be incomplete; missing evidence must be reported rather than treated as a completed, successful investigation.

A product exporter is any executable taking a user-owned request JSON on stdin and returning one `archive-v1` object on stdout. Invoke it with:

```sh
python3 -m bench adapter --request request.json --out runs/archive.json -- python3 my_exporter.py
```

To import an investigation manually, save the product's final answer as `final.txt`, earlier messages as `intermediate.txt`, and tool calls and results as `actions.txt` in the case directory. Then run `python3 -m bench archive`. Only `final.txt` is required; leave unavailable messages or actions missing.

To automate collection, write a script that reads your product's API and returns the investigation record described below. Run that script through `python3 -m bench adapter`. Product-specific collection scripts are not included yet.

Use the final answer delivered to the user and apply the same selection rule to every investigation. Earlier answers belong in the intermediate messages, even when they contain a better recommendation.

Required investigation record format (`archive-v1`):

```json
{
  "schema_version": "archive-v1",
  "run_id": "example-run",
  "case_id": "example-case",
  "product": "user-defined-label",
  "scenario": "crashloop",
  "detection": {"status": "not_measured"},
  "final_selection": "How the delivered final answer was selected",
  "sources": {
    "final_answer": "Verbatim final delivered answer",
    "intermediate": "Earlier prose, or empty when unavailable",
    "actions": "Recorded submissions and results, or empty when unavailable"
  },
  "limitations": ["State missing records and selection uncertainty"]
}
```

Detection states: detected, not_detected, not_measured. A detected label needs independent evidence and a declared observation window in the run's own records. The starter records but does not independently verify operator-entered detection. Additional source entries may hold contemporaneous PR context or other evidence; record author/timestamps and do not attribute another investigator's work to the evaluated product.

The packet is **judge-only**: it contains ground truth. Never send it to a product being investigated. Give product adapters only product request inputs and accessible operational evidence. Treat exported prose as sensitive until reviewed: collectors may include user data. No secret resource collection is performed by `evidence`, but logs can still contain secrets from a user-modified workload.

## Judge configuration

For the standard setup, follow [How to score investigations](../README.md#how-to-score-investigations). You only need a provider, a model name and its API key.

Choose a provider using this table:

| `judge.provider` | Put your API key in this environment variable |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai-compatible` | `ARENA_JUDGE_API_KEY`; also set `base_url` |

Keep the actual key in your shell environment. The configuration stores only the name of the variable that contains it.

### OpenRouter

OpenRouter works through the existing `openai-compatible` provider. Set the judge section to:

```json
"judge": {
  "provider": "openai-compatible",
  "base_url": "https://openrouter.ai/api/v1",
  "api_key_env": "OPENROUTER_API_KEY",
  "model": "YOUR_OPENROUTER_MODEL_ID"
}
```

Create a key in [OpenRouter's key settings](https://openrouter.ai/settings/keys) and make it available as `OPENROUTER_API_KEY`. Choose an explicit model ID that supports JSON responses. Use the same model and routing settings across compared products. The raw response is retained with each attempt, including provider information when supplied. See the [OpenRouter API guide](https://openrouter.ai/docs/quickstart).

### Local models

For a local server that supports the chat completions API and JSON responses, edit the `judge` section:

```json
"judge": {
  "provider": "openai-compatible",
  "model": "YOUR_SERVED_MODEL",
  "base_url": "http://localhost:8000/v1",
  "api_key_env": ""
}
```

The empty `api_key_env` means this local server needs no key. Remote endpoints require HTTPS.

### Optional settings

Defaults work without these fields. Add them only if needed:

| Setting | Purpose | Default |
|---|---|---|
| `max_output_tokens` | Maximum response length | `8192` |
| `timeout` | API request timeout in seconds | `180` |
| `temperature` | Model sampling setting, if supported | Provider default |
| `reasoning_effort` | Reasoning setting for supported OpenAI API formats | Provider default |
| `api_key_env` | Use a different credential environment variable | From the provider table |

### Custom judge scripts

If the built-in providers do not cover your setup, set `judge_command` to `["python3", "/path/to/your_judge.py"]`. This overrides `judge`. The script reads the prepared packet from stdin and writes the [judge response](#judge-response) to stdout. It handles its own authentication and saves its own API responses.

### Rescoring and saved results

Existing files are never overwritten. To score a saved investigation again:

```sh
python3 -m bench packet --out runs/demo/oom/packet-review.json
python3 -m bench judge --packet runs/demo/oom/packet-review.json \
  --out runs/demo/oom/judgment-review.json
```

Replace the example paths with your case directory. Change the judge settings first if you want to compare models. Rescoring cannot recover messages or actions that were never captured.

The built-in judge keeps each request, the provider response when available, and validation status in `judge-attempts/` beside the result. Invalid or incomplete responses produce an error instead of a score. There is no automatic retry or fallback model.

For a customized scenario, supply its matching answer key with `packet --truth path/to/key.json`. Keep answer keys and prepared packets separate from the product being evaluated.

## Judge response

This section is for custom judge scripts. The built-in judge handles this format for you.

Copy case_id, archive_sha256, rubric_sha256, truth_sha256 from packet. Supply `judge` with provider, model_or_reviewer and settings. Each of the seven dimensions listed in packet.allowed_verdicts has:

```json
{
  "verdict": "supported",
  "rationale": "Explain the decision and coverage.",
  "evidence": [{"source_id": "final_answer", "quote": "Exact nonempty substring"}]
}
```

Dimensions: final_quality, implementation_readiness, action_safety, intermediate_advice, rca, blast_radius, causal_change. Finish with a limitations array.

The validator checks identity/hashes, enums, judge provider and settings and exact citations. It does not prove the reasoning is correct. Judges require calibration and manual audit. Missing action/intermediate records must receive insufficient_evidence. Use the same final selection rule, rubric hash, judge configuration and evidence-access policy for every compared product. Custom rubric text is supported within this response format; a new set of output dimensions requires an explicitly versioned schema/code change.

## Reproducibility and current limits

Investigation records are create-only and canonical-content hashed in packets. Version control rubric changes and keep old judgment files. The built-in judge retains attempts as described above; custom judge commands must retain their own raw responses.

The main `python3 -m bench` deploy, fault, verify, reset and evidence commands save operation timing, selected configuration, source hashes and cluster snapshots under the case's `operations/` directory. The `bench.scenarios` deploy/start/verify/reset commands use the same recording wrapper and read output settings from `arena.json`. Snapshots include workload state, image IDs, events and bounded logs; they are not continuous telemetry. Logs can contain sensitive application output, so review files before sharing them.

Record product settings, collector configuration, and the detection timestamp and observation window separately. Detection is operator-reported; the runner does not poll a vendor or align its clock. A successful benchmark reset is not evidence that the evaluated product repaired the incident.

Full-suite investigation records set `suite` to `full`; their scenario must be in scenarios/scenarios.json. Packet construction loads the bundled `scenarios/faults/<scenario>/answer-key.json` automatically. Use `--truth` only to override it for a customized deployment; the replacement must match the scenario and include cause, impact and mitigation. The smoke default uses separately defined fixture ground truth.


Return to the [usage guide](../README.md#how-to-connect-your-product).
