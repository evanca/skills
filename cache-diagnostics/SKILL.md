---
name: cache-diagnostics
description: Use when prompt cache hit rate is low or unexplained, cache_read_input_tokens drops to zero, an agent loop or chatbot costs more per turn than expected, or someone asks why the Claude prompt cache keeps missing.
---

# Diagnosing prompt cache misses

Prompt caching only works when the beginning of a request is **byte-for-byte
identical** to a recent one. A reordered tool, a timestamp interpolated into a
system prompt, or an edited earlier message silently invalidates it. Without
diagnostics the only signal is `usage.cache_read_input_tokens` dropping to zero,
with no indication of what changed.

Cache diagnostics closes that gap: pass the `id` of the previous response, and
the API compares the two requests and reports **where they first diverged**.

- Beta header: `cache-diagnosis-2026-04-07`
- Endpoint: the **beta** namespace — `client.beta.messages.create` / `.stream`
- **Claude API only.** Not on Claude Platform on AWS, Amazon Bedrock, Google
  Cloud, or Microsoft Foundry.
- ZDR eligible. Fingerprints are hashes and token-count estimates only — never
  raw prompt content.

## Do this first: is there actually a problem?

Read `usage.cache_read_input_tokens` across several consecutive turns before
reaching for diagnostics.

- **High and stable** — the cache is working. Stop; there is nothing to fix.
- **Zero on the first turn** — normal. The cache is being *written*, not read.
- **Zero or low on later turns** — this is what diagnostics is for.

Also check the prefix is long enough to cache at all: the minimum cacheable
prefix is model-dependent (512–4096 tokens). A shorter prefix silently never
caches, and diagnostics will not report that as a divergence.

## The two-turn probe

Send the beta header on **every** turn. Turn 1 passes
`previous_message_id: null` to opt in with nothing to compare against; every
later turn passes the `id` from the previous response.

```python
import anthropic
client = anthropic.Anthropic()

SYSTEM = "You are an AI assistant analyzing a large document. <document>...</document>"

r1 = client.beta.messages.create(
    model="claude-opus-5",
    max_tokens=1024,
    cache_control={"type": "ephemeral"},
    system=SYSTEM,
    messages=[{"role": "user", "content": "Summarize section 1."}],
    diagnostics={"previous_message_id": None},
    betas=["cache-diagnosis-2026-04-07"],
)

r2 = client.beta.messages.create(
    model="claude-opus-5",
    max_tokens=1024,
    cache_control={"type": "ephemeral"},
    system=SYSTEM,
    messages=[
        {"role": "user", "content": "Summarize section 1."},
        {"role": "assistant", "content": r1.content},   # verbatim, not the text
        {"role": "user", "content": "Now summarize section 2."},
    ],
    diagnostics={"previous_message_id": r1.id},
    betas=["cache-diagnosis-2026-04-07"],
)

d = r2.diagnostics
if d is None:
    print("No divergence detected.")
elif d.cache_miss_reason is None:
    print("Comparison still pending — check the next turn.")
else:
    print(d.cache_miss_reason.type, d.cache_miss_reason.cache_missed_input_tokens)
```

`scripts/diagnose_cache.py` in this skill runs exactly this against your own
system prompt and tool list and prints the verdict.

**In a conversation loop**, carry the latest response `id` forward as
`previous_message_id` on every iteration — `prev_id = None` before the loop,
`prev_id = r.id` at the end of each pass.

**When streaming**, `diagnostics` arrives on the `message_start` event and is
carried through to `stream.get_final_message()` / `.finalMessage()` /
`accumulated_message`.

## Reading the answer

`diagnostics` has four states, and three of them are not findings:

| Value | Meaning |
|---|---|
| field absent | No `diagnostics` in the request, or the beta header was missing. |
| `null` | Either first turn (`previous_message_id: null`), or a comparison ran and found **no divergence**. |
| `{"cache_miss_reason": null}` | Comparison still running when the response was serialized. Inconclusive — check the next turn. |
| `{"cache_miss_reason": {...}}` | A real result. See the table below. |

Only the **earliest** divergence is reported. Fix it first; later ones may be
hidden behind it.

| `type` | Cause | Fix |
|---|---|---|
| `model_changed` | A router, A/B test, or fallback picked a different model. The cache is per-model. | Hold the model constant for the life of a cached conversation. |
| `system_changed` | A timestamp, request id, or other per-request value was interpolated into `system`. | Make `system` a byte-stable constant; move dynamic data into the first `user` message after the breakpoint. |
| `tools_changed` | Tools added, removed, reordered, or `input_schema` serialized non-deterministically. | Same list, fixed order, sorted JSON keys. |
| `messages_changed` | An earlier `messages` entry was altered, reordered, or removed instead of appended to — often truncated history, or assistant/`tool_result` blocks re-serialized on resend. | Treat history as append-only; echo assistant `content` and tool results back verbatim. |
| `previous_message_not_found` | No stored fingerprint for that id. **Not evidence your request changed** — usually the previous turn lacked the beta header, ran in another workspace, or was too long ago. | Send the header on every turn; keep turns close together. |
| `unavailable` | No comparison produced. Includes the case where model/system/tools all match but another prompt-affecting parameter differs — `tool_choice`, `thinking`, `context_management`, `output_config`, `output_format`, or the active `anthropic-beta` set — and conversations longer than the comparison horizon. | Hold those parameters constant too. |

The four `*_changed` types also carry **`cache_missed_input_tokens`**: an
estimate of how much cacheable prefix was lost. It is derived from byte lengths
before tokenization, so read it as a magnitude, never as a billing number — it
can differ from and occasionally exceed `usage.input_tokens`.

## Combining with usage

`diagnostics` answers *did my request change?*; `cache_read_input_tokens`
answers *did the cache hit?*. Both are needed. This matrix applies only to turns
that passed a real `previous_message_id`, and not when `cache_miss_reason` is
`null`, `previous_message_not_found`, or `unavailable`.

| Diagnostics | Cache reads | Interpretation |
|---|---|---|
| `null` | high | Working. Stop here. |
| `null` | low or zero | Requests match; the entry expired. Shorten the gap between turns, or use the 1-hour cache TTL. |
| a `*_changed` type | low or zero | Your bug. Fix the cause its `type` names. |
| a `*_changed` type | high | Rare. Change landed late in the prompt and an earlier breakpoint still hit. Low impact. |

## Limits worth stating before you trust a result

- **Beta** — field names and semantics may change.
- **Fingerprints expire quickly.** Compare closely spaced requests.
- **Same organization and workspace.** Compare the `anthropic-workspace-id`
  response header on the two responses if unsure.
- **Comparison horizon.** In very long conversations where the only change is
  deep in the message list, expect `unavailable` rather than a precise location.
- **Best-effort.** Diagnostics never blocks or fails the request, so a missing
  result is not a failure signal.

## Fixing what it finds

Diagnostics names the divergence; the durable fix is prefix stability. Render
order is `tools` → `system` → `messages`, so keep stable content first and put
volatile content (timestamps, per-request ids, the varying question) after the
last `cache_control` breakpoint. Max 4 breakpoints per request.
