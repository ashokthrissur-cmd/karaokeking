---
name: agent-skill-authoring
description: Creates, validates, and installs Agent Skills (SKILL.md folders) following the open Agent Skills specification. Covers required frontmatter fields, name and description constraints, progressive disclosure with references/ and scripts/, writing descriptions that trigger correctly, and validating with the skills-ref CLI. Use when adding a new skill, fixing a skill that will not load, or setting up a skills directory for an agent.
license: Apache-2.0
metadata:
  author: karaokeking
  version: "1.0"
---

# Authoring Agent Skills

## What a skill is

A directory containing `SKILL.md` with YAML frontmatter plus Markdown
instructions. Optional `scripts/`, `references/`, `assets/` sit alongside.

```
my-skill/
├── SKILL.md          # required
├── scripts/          # executable helpers
├── references/       # docs loaded on demand
└── assets/           # templates, fonts, fixtures
```

## Required frontmatter

```yaml
---
name: pdf-processing
description: Extracts text and tables from PDFs, fills forms, merges files. Use when working with PDF documents.
---
```

### `name` rules (enforced by the validator)

- 1–64 characters
- lowercase letters, digits, hyphens only
- no leading or trailing hyphen
- no consecutive hyphens (`--`)
- **must exactly match the parent directory name**

### `description` rules

- 1–1024 characters, non-empty
- must state **what it does** *and* **when to use it**
- include the words a user would actually type

Weak: `Helps with PDFs.`
Strong: `Extracts text and tables from PDF files, fills PDF forms, merges
multiple PDFs. Use when working with PDF documents or when the user mentions
PDFs, forms, or document extraction.`

The description is the only thing loaded at startup, so it is the entire basis
for the activation decision. Spend effort here.

### Optional fields

| Field | Notes |
|---|---|
| `license` | Short name or a bundled LICENSE file |
| `compatibility` | Max 500 chars; only if there are real environment requirements |
| `metadata` | String→string map; use unique keys |
| `allowed-tools` | Space-separated, experimental |

Any other top-level key is a validation error.

## Progressive disclosure

`SKILL.md` should stay under ~500 lines / 5,000 tokens. Everything in it loads
into context on activation, competing with the conversation.

When a skill needs more, move detail into `references/` and tell the agent
**when** to read each file:

```markdown
Read `references/api-errors.md` if the API returns a non-200 status.
```

That is far more useful than "see references/ for details", which the agent
will either always follow or never follow.

## Writing rules that actually help

1. **Add what the agent lacks, omit what it knows.** Do not explain what a PDF
   is. Do explain your project's exact command, flag, or convention.
2. **Ground it in real work.** A skill extracted from an actual debugging
   session — including the wrong turns — beats one generated from general
   knowledge. The corrections are the valuable part.
3. **Match specificity to fragility.** Fragile sequences get exact commands.
   Judgment calls get criteria and the reasoning behind them.
4. **One coherent unit.** Too narrow and several skills must load at once; too
   broad and activation becomes imprecise.
5. **Show a working example.** One runnable snippet outperforms three
   paragraphs of description.

## Validate before shipping

```bash
pip install -e skills-ref
skills-ref validate path/to/my-skill
```

Empty output means valid. Non-empty lists the exact problems.

Other commands:

```bash
skills-ref read-properties path/to/my-skill    # JSON of frontmatter
skills-ref to-prompt path/to/a path/to/b       # <available_skills> XML
```

## Installing skills for an agent

Common locations, in order of preference:

```
./skills/                 # project-local, version controlled
~/.claude/skills/         # user-global for Claude Code
```

A project-local `skills/` directory is best: it travels with the repo, so the
knowledge is available to anyone who clones it.

Generate the discovery block for a system prompt with:

```bash
skills-ref to-prompt skills/*/ > available_skills.xml
```

```xml
<available_skills>
<skill>
<name>my-skill</name>
<description>What it does and when to use it</description>
<location>/abs/path/my-skill/SKILL.md</location>
</skill>
</available_skills>
```

## Common validation failures

| Error | Fix |
|---|---|
| `Directory name 'X' must match skill name 'Y'` | Rename the folder or the `name` field so they match |
| `Skill name must be lowercase` | Lowercase the `name` |
| `contains invalid characters` | Use only `a-z0-9-`; underscores and spaces are invalid |
| `Unexpected fields in frontmatter` | Remove non-spec keys; put them under `metadata` |
| `Description exceeds 1024 characters` | Trim; move detail into the body |

## Checklist

- [ ] Folder name == `name` field, lowercase, hyphenated
- [ ] Description says what *and* when, with real trigger words
- [ ] `SKILL.md` under 500 lines
- [ ] Long detail moved to `references/`, with explicit load conditions
- [ ] At least one concrete, runnable example
- [ ] `skills-ref validate` returns nothing
