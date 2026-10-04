#!/usr/bin/env bash
# The only way this repo calls Codex (OpenAI). Make targets call this; nobody calls codex by hand.
#
#   pipeline/codex_run.sh <step> <batch-file> <out-file>     (relative paths: from the repo root)
#
#   <step>        name of pipeline/prompts/<step>.md and pipeline/prompts/<step>.schema.json
#   <batch-file>  the input for this one call (JSON); it is copied into a scratch dir outside the repo
#   <out-file>    where the model's JSON answer goes; must be under work/ or data/raw/ (both
#                 gitignored). Committed files are written only after validate.py passes.
#
# Locked down by design (see the README, "How OpenAI Codex was used"): scratch dir outside the repo, prompt and batch
# on stdin so Codex needs no file reads, environment stripped, read-only sandbox, no approvals, web
# search disabled, strict output schema, model pinned. pipeline/codex_check.py then fails the run
# closed unless every event is on its allowlist (no tool of any kind) and the answer matches the
# schema. Events logs and provenance sidecars stay in gitignored data/raw/codex-runs/ (override with
# CODEX_RUNS_DIR for tests; CODEX_BIN then points the tests at a stub). OPENAI_API_KEY is never
# set; authentication reuses the human's one-time `codex login` through CODEX_HOME (shell
# environment, not .env).
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <step> <batch-file> <out-file>" >&2
  exit 2
fi

step="$1"
batch="$2"
out="$3"
model="gpt-6-astra"   # pinned so provenance names the exact model

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
codex="$repo/node_modules/.bin/codex"
python="$repo/.venv/bin/python"
prompt="$repo/pipeline/prompts/$step.md"
schema="$repo/pipeline/prompts/$step.schema.json"
runs_dir="${CODEX_RUNS_DIR:-$repo/data/raw/codex-runs}"
if [ -n "${CODEX_BIN:-}" ]; then   # test stub: only with a runs dir outside the real data folder
  runs_real="$("$python" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${CODEX_RUNS_DIR:-}")"
  case "$runs_real" in
    "$repo"/data/*|"$repo") echo "codex_run: CODEX_BIN needs CODEX_RUNS_DIR outside data/" >&2; exit 2 ;;
  esac
  codex="$CODEX_BIN"
fi
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$step-$$"

for f in "$prompt" "$schema" "$batch" "$codex" "$python"; do
  [ -e "$f" ] || { echo "codex_run: missing $f" >&2; exit 2; }
done
out_real="$("$python" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$out")"
case "$out_real" in
  "$repo"/work/*|"$repo"/data/raw/*) ;;
  *) echo "codex_run: <out-file> must be under work/ or data/raw/, got $out" >&2; exit 2 ;;
esac
mkdir -p "$runs_dir"
rm -f "$out"

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
cp "$batch" "$scratch/input.json"

events="$runs_dir/$run_id.events.jsonl"
answer="$scratch/out.json"

# stdin = prompt file, then the batch wrapped as data.
{
  cat "$prompt"
  printf '\n\n<input format="json">\n'
  cat "$scratch/input.json"
  printf '\n</input>\n'
} | env -i \
    PATH="$PATH" \
    HOME="$HOME" \
    CODEX_HOME="${CODEX_HOME:-$HOME/.codex}" \
    "$codex" exec \
      -C "$scratch" \
      --skip-git-repo-check \
      --ephemeral \
      --ignore-user-config \
      -m "$model" \
      -s read-only \
      -c approval_policy=never \
      -c web_search=disabled \
      -c shell_environment_policy.inherit=none \
      --output-schema "$schema" \
      -o "$answer" \
      --json - > "$events"

if ! "$python" -m pipeline.codex_check "$events" "$answer" "$schema"; then
  echo "codex_run: REJECTED batch $run_id (see $events)" >&2
  exit 3
fi

mkdir -p "$(dirname "$out")"
cp "$answer" "$out"

# Provenance sidecar, in the shape of schema.Provenance. Never a request URL.
cat > "$runs_dir/$run_id.meta.json" <<EOF
{
  "agent": "codex",
  "model": "$model",
  "tool_version": "$("$codex" --version | awk '{print $NF}')",
  "run_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "prompt_sha256": "$(shasum -a 256 "$prompt" | cut -d' ' -f1)",
  "input_manifest_sha256": "$(shasum -a 256 "$scratch/input.json" | cut -d' ' -f1)",
  "extractor_run_id": "$run_id",
  "step": "$step",
  "output_sha256": "$("$python" -c 'import hashlib, json, sys; d = json.load(open(sys.argv[1])); print(hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())' "$answer")"
}
EOF
echo "codex_run: ok $run_id -> $out"
