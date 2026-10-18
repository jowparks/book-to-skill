#!/usr/bin/env bash
# Convert a PDF to Markdown with marker's LLM pass (equations as LaTeX) before
# book-to-skill extraction. Marker is a separate tool, not a book-to-skill
# dependency.
#
# Usage: marker_convert.sh [--sample] <file.pdf> <output-dir>
#
# The API key comes from ANTHROPIC_API_KEY or OPENAI_API_KEY when set,
# otherwise it is read (hidden) from the terminal. The provider is detected
# from the key prefix: sk-ant-… is Claude, any other sk-… is OpenAI.
# MARKER_MODEL overrides the model. --sample converts only the first pages
# so the output can be checked before a full run.
#
# On success the last line of stdout is the path of the generated Markdown.
set -euo pipefail

CLAUDE_MODEL="claude-sonnet-5-5"
OPENAI_MODEL="gpt-5-mini"
SAMPLE_PAGES="0-30"

die() { printf 'marker_convert: %s\n' "$2" >&2; exit "$1"; }

sample=false
if [ "${1:-}" = "--sample" ]; then sample=true; shift; fi
[ $# -eq 2 ] || die 64 "usage: marker_convert.sh [--sample] <file.pdf> <output-dir>"
pdf=$1
out_dir=$2
[ -f "$pdf" ] || die 66 "not a file: $pdf"

command -v marker_single >/dev/null 2>&1 ||
  die 2 "marker_single not found; install it with: pip install marker-pdf"

if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ -n "${OPENAI_API_KEY:-}" ]; then
  die 64 "both ANTHROPIC_API_KEY and OPENAI_API_KEY are set; unset one"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  key=$ANTHROPIC_API_KEY
elif [ -n "${OPENAI_API_KEY:-}" ]; then
  key=$OPENAI_API_KEY
elif { : </dev/tty; } 2>/dev/null; then
  printf 'API key for marker (Claude or OpenAI, input hidden): ' >/dev/tty
  IFS= read -rs key </dev/tty
  printf '\n' >/dev/tty
else
  die 3 "no API key: export ANTHROPIC_API_KEY or OPENAI_API_KEY, or run this in a terminal"
fi

case $key in
  sk-ant-*) provider=claude ;;
  sk-*) provider=openai ;;
  "") die 3 "no API key given" ;;
  *) die 3 "unrecognized API key format (expected sk-ant-… for Claude or sk-… for OpenAI)" ;;
esac

# The key goes into a private config file, not argv, so it never shows up in
# the process list.
umask 077
config=$(mktemp "${TMPDIR:-/tmp}/marker-config.XXXXXX")
trap 'rm -f "$config"' EXIT
json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
# marker reads llm_service only from the command line, so it stays in argv.
if [ "$provider" = claude ]; then
  service=marker.services.claude.ClaudeService
  model=${MARKER_MODEL:-$CLAUDE_MODEL}
  printf '{"claude_api_key": "%s", "claude_model_name": "%s"}\n' \
    "$(json_escape "$key")" "$(json_escape "$model")" >"$config"
else
  service=marker.services.openai.OpenAIService
  model=${MARKER_MODEL:-$OPENAI_MODEL}
  printf '{"openai_api_key": "%s", "openai_model": "%s"}\n' \
    "$(json_escape "$key")" "$(json_escape "$model")" >"$config"
fi
unset key

args=(--use_llm --llm_service "$service" --redo_inline_math --output_format markdown --config_json "$config" --output_dir "$out_dir")
if $sample; then args+=(--page_range "$SAMPLE_PAGES"); fi

printf 'marker_convert: %s via %s (%s)%s\n' "$pdf" "$provider" "$model" \
  "$($sample && printf ', sample pages %s' "$SAMPLE_PAGES")" >&2
marker_single "$pdf" "${args[@]}" >&2

stem=$(basename "$pdf")
stem=${stem%.*}
md="$out_dir/$stem/$stem.md"
[ -f "$md" ] || die 1 "marker finished but $md was not created"
printf '%s\n' "$md"
