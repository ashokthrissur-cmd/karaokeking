# Skills

Agent Skills for this workspace, in the open
[Agent Skills](https://agentskills.io) format: a folder per skill containing a
`SKILL.md` with YAML frontmatter.

## Installed skills

| Skill | Use it when |
|---|---|
| [`windows-python-app-packaging`](windows-python-app-packaging/SKILL.md) | Packaging a Python/PySide6 app as a self-contained Windows `.exe`, or debugging "installed but won't open" |
| [`karaoke-video-pipeline`](karaoke-video-pipeline/SKILL.md) | Generating karaoke videos: vocal removal, lyric fetch, sync, ASS rendering |
| [`agent-skill-authoring`](agent-skill-authoring/SKILL.md) | Adding a new skill or fixing one that won't load |

## Layout

```
skills/
├── <skill-name>/
│   ├── SKILL.md          # required: frontmatter + instructions
│   ├── references/       # optional: docs loaded on demand
│   └── scripts/          # optional: runnable helpers
└── .reference/           # vendored spec + authoring guides (not a skill)
```

The `.reference/` folder holds the upstream specification and best-practice
guides so they are available offline. It is dot-prefixed so `skills/*/` globs
skip it.

## Validate

```bash
pip install -e /path/to/agentskills/skills-ref
skills-ref validate skills/*/
```

Every skill must pass with no output before being committed.

## Install for an agent

```bash
./install.sh            # symlink into ~/.claude/skills
./install.sh --copy     # copy instead of symlink
```

## Add a new skill

```bash
mkdir -p skills/my-skill
cat > skills/my-skill/SKILL.md <<'EOF'
---
name: my-skill
description: What it does, and when to use it. Include the words a user would type.
---

# My Skill

Instructions...
EOF
skills-ref validate skills/my-skill
```

The folder name and the `name` field must match exactly. See
`agent-skill-authoring` for the full set of rules.

## Generate the discovery block

```bash
skills-ref to-prompt skills/*/ > available_skills.xml
```

Paste that into a system prompt so the agent knows which skills exist without
loading all of them.
