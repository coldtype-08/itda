# ItDA OpenShell policy

| File | What it is |
|---|---|
| `openshell-policy.yaml` | Submission policy, least privilege. Filesystem: code, task and `input/` read-only, `output/` the only writable app path, no `restricted/` or `secrets/`. Landlock `hard_requirement`, non-root `sandbox` user. Network: NIM only (`inference.local` chat completions + the local Nano NIM). |
| `presets/` | Service-mode add-ons, one public API per NeMoClaw preset, each limited to method + path + `/opt/venv/bin/python3`. |
| `itda-hack.policy.yaml` | Export of the policy actually applied to the demo sandbox (NemoClaw Restricted tier + the presets above). |
| `itda-hack.presets.txt` | Preset list of the demo sandbox at export time. |

The sandbox layout used by `scripts/sandbox_run.sh` matches `openshell-policy.yaml`:

    /sandbox/itda                    code        read-only
    /sandbox/pack/TASK.md            request     read-only
    /sandbox/pack/hackathon/input    documents   read-only
    /sandbox/pack/hackathon/output   results     read-write

`filesystem_policy`, `landlock` and `process` are fixed when a sandbox is created; `network_policies` can be changed on a running sandbox.

Apply a preset (service mode), previewing first:

    nemo-deepagents itda-hack policy add --from-file policy/presets/itda-tmap.yaml --dry-run

Export the policy actually applied to the sandbox and commit it here:

    sh scripts/export_policy.sh
