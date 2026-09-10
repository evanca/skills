#!/usr/bin/env python3
"""Run the two-turn cache-diagnostics probe against your own prompt.

Answers one question: when this prompt is sent twice, does the prefix stay
byte-identical, and if not, WHERE does it first diverge?

    python3 diagnose_cache.py --system-file prompts/system.txt
    python3 diagnose_cache.py --system-file prompts/system.txt --tools-file tools.json
    python3 diagnose_cache.py --system-file prompts/system.txt --model claude-sonnet-5

The two turns are sent back to back with an identical prefix, so a divergence
reported here is a defect in how YOU build the request (a timestamp in the
system prompt, non-deterministic tool-schema serialization), not a property of
the conversation. That is the point: it reproduces the bug in isolation.

Requires: pip install anthropic, and credentials (ANTHROPIC_API_KEY, or an
`ant auth login` profile the SDK picks up from a zero-arg client).

Claude API only — cache diagnostics is not available on Claude Platform on AWS,
Amazon Bedrock, Google Cloud, or Microsoft Foundry.
"""

import argparse
import json
import pathlib
import sys

BETA = "cache-diagnosis-2026-04-07"

FIXES = {
    "model_changed": "A different model was selected between turns. The cache is per-model — hold it constant for the life of a cached conversation.",
    "system_changed": "The system prompt is not byte-stable. Something per-request (a timestamp, a request id, a user name) is interpolated into it. Make `system` constant and move the varying part into the first user message after your last cache_control breakpoint.",
    "tools_changed": "The tools array differs between turns: added, removed, reordered, or the input_schema JSON serialized non-deterministically. Send the same list in a fixed order and sort schema keys before serializing.",
    "messages_changed": "An earlier message was altered, reordered, or removed rather than appended to. Treat history as append-only and echo assistant content and tool_result blocks back VERBATIM — re-serializing them counts as a change.",
    "previous_message_not_found": "No stored fingerprint for the previous id. This is NOT evidence your request changed — usually the previous turn was missing the beta header, ran in another workspace, or was too long ago. Send the header on every turn.",
    "unavailable": "No comparison was produced. Often means model/system/tools all match but another prompt-affecting parameter differs — tool_choice, thinking, context_management, output_config, output_format, or the active anthropic-beta set. Hold those constant too.",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system-file", required=True, help="File holding the system prompt to test.")
    ap.add_argument("--tools-file", help="Optional JSON file holding the tools array.")
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--max-tokens", type=int, default=64,
                    help="Small on purpose: this probe measures the PREFIX, not the output.")
    args = ap.parse_args()

    try:
        import anthropic
    except ImportError:
        print("pip install anthropic", file=sys.stderr)
        return 2

    system = pathlib.Path(args.system_file).read_text()
    tools = json.loads(pathlib.Path(args.tools_file).read_text()) if args.tools_file else None

    client = anthropic.Anthropic()
    common = dict(model=args.model, max_tokens=args.max_tokens,
                  cache_control={"type": "ephemeral"}, system=system,
                  betas=[BETA])
    if tools:
        common["tools"] = tools

    print(f"model={args.model}  system={len(system)} chars  tools={len(tools) if tools else 0}")

    r1 = client.beta.messages.create(
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        diagnostics={"previous_message_id": None}, **common)
    print(f"turn 1  cache_write={r1.usage.cache_creation_input_tokens} "
          f"cache_read={r1.usage.cache_read_input_tokens}")

    r2 = client.beta.messages.create(
        messages=[
            {"role": "user", "content": "Reply with the single word: ok"},
            {"role": "assistant", "content": r1.content},
            {"role": "user", "content": "Reply with the single word: ok"},
        ],
        diagnostics={"previous_message_id": r1.id}, **common)
    print(f"turn 2  cache_write={r2.usage.cache_creation_input_tokens} "
          f"cache_read={r2.usage.cache_read_input_tokens}")

    d = r2.diagnostics
    print()
    if d is None:
        if r2.usage.cache_read_input_tokens > 0:
            print("PASS — prefix is stable and the cache hit.")
            return 0
        print("INCONCLUSIVE — no divergence found, but nothing was read from cache.")
        print("The requests match; the cache entry was not available. Either the prefix is")
        print("below the model's minimum cacheable length (512-4096 tokens, model-dependent),")
        print("or the entry expired. Consider the 1-hour cache TTL for sparse traffic.")
        return 0
    if d.cache_miss_reason is None:
        print("PENDING — the comparison had not finished when the response was serialized.")
        print("Inconclusive by design; re-run, or check the next turn in a real loop.")
        return 0

    t = d.cache_miss_reason.type
    missed = getattr(d.cache_miss_reason, "cache_missed_input_tokens", None)
    print(f"DIVERGENCE: {t}")
    if missed is not None:
        print(f"~{missed} input tokens of cacheable prefix lost (magnitude, not a billing number)")
    print()
    print(FIXES.get(t, "Unrecognized type — check the cache-diagnostics docs; this is a beta surface."))
    print()
    print("Only the EARLIEST divergence is reported. Fix this one, then re-run — another")
    print("may be hidden behind it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
