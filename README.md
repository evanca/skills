# Claude API skills

Agent skills for the Claude API. They install into Claude Code, Codex, and any runtime that loads
a `SKILL.md`.

## Skills

### [`cache-diagnostics`](cache-diagnostics/SKILL.md)

Find out why a Claude prompt cache keeps missing.

Prompt caching works only when a request starts byte-for-byte identical to a recent one. Reorder a
tool, interpolate a timestamp into a system prompt, edit an earlier message, and the cache stops
hitting. You get one symptom: `usage.cache_read_input_tokens` falls to zero. Nothing tells you
which change caused it. On a long agent loop you then pay full input price for a prefix you meant
to read from cache.

The skill uses the `cache-diagnosis-2026-04-07` beta, which compares two consecutive requests and
reports the first point where they diverged. It covers:

- Six `cache_miss_reason` types (`model_changed`, `system_changed`, `tools_changed`,
  `messages_changed`, `previous_message_not_found`, `unavailable`) with the fix for each.
- Three response states that look like findings and aren't: field absent, `null`, and a comparison
  that hadn't finished.
- The diagnostics-vs-`usage` matrix. "Did my request change?" and "did the cache hit?" are separate
  questions, and you need both answers to know where to look.
- The limits that make a result untrustworthy: short fingerprint retention, same-workspace
  comparison, the horizon on long conversations, best-effort semantics.

It bundles [`scripts/diagnose_cache.py`](cache-diagnostics/scripts/diagnose_cache.py), a probe that
sends an identical prefix twice against your own system prompt and tool list:

```bash
python3 cache-diagnostics/scripts/diagnose_cache.py --system-file prompts/system.txt
python3 cache-diagnostics/scripts/diagnose_cache.py --system-file prompts/system.txt --tools-file tools.json
```

Both turns carry the same prefix, so any divergence points at your request-building code. The probe
names the miss reason, how much cacheable prefix you lost, and what to change.

Install `anthropic` and set credentials first: `ANTHROPIC_API_KEY`, or an `ant auth login` profile,
which a zero-argument client picks up.

Cache diagnostics runs on the Claude API only. Claude Platform on AWS, Amazon Bedrock, Google Cloud
and Microsoft Foundry do not support it.

It is a beta, so Anthropic can change field names and semantics. Check the tables against the
[current documentation](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics)
before you rely on them.

## Install

With the [`skills` CLI](https://www.skills.sh/docs/cli):

```bash
npx skills add evanca/skills --skill cache-diagnostics
```

Or copy the directory. For every project on the machine:

```bash
cp -R cache-diagnostics ~/.claude/skills/
```

For one project:

```bash
cp -R cache-diagnostics <project>/.claude/skills/
```

Claude Code reads `~/.claude/skills/` and `<project>/.claude/skills/`, and triggers a skill from
the `description` in its frontmatter. Codex reads `~/.codex/skills/`. Antigravity reads
`~/.gemini/config/skills/`.

## Source and credits

Anthropic owns the behaviour this skill describes, and Anthropic's documentation is the authority
on it:

- [Cache diagnostics](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics)
  documents the `cache-diagnosis-2026-04-07` beta: the request shape, every `cache_miss_reason`
  type, the response states, and the limits.
  [`cache-diagnostics/SKILL.md`](cache-diagnostics/SKILL.md) condenses that page.
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) documents
  the underlying feature, including the prefix rules and the troubleshooting checklist a
  diagnostics result sends you back to.

Claude wrote the skill and the probe script by reading those two pages on 2026-09-10 rather than
recalling them.

Trust the source page over this skill wherever they disagree. Anthropic can change a beta, and this
copy will not know. Anthropic has not reviewed or endorsed this repository.

## License

[MIT](LICENSE). Copyright (c) 2026 Ivanna Kaceviča.

The grant covers this repository. Anthropic's documentation, which the skill condenses, stays
Anthropic's.
