# Understanding Your Token Budget

> "Context windows are arrays. The less that window needs to slide, the better."

## The Reality

| Advertised | Actual Usable |
|------------|---------------|
| 200K tokens | ~176K tokens |

Where'd the rest go?
- ~16K: Model system overhead
- ~16K: Harness overhead (tool definitions, etc.)

## Mental Model

**One Star Wars Episode 1 script = ~60K tokens = ~136KB on disk**

You can fit **1-2 movie scripts** of context. That's it.

## Budget Per Ralph Loop

| Component | Tokens | Notes |
|-----------|--------|-------|
| Model overhead | ~16K | Fixed, unavoidable |
| Harness overhead | ~16K | Fixed, unavoidable |
| Specs (Pin) | ~5K | Your specs/README.md lookup table |
| Implementation plan | ~2K | The task checklist |
| Prompt | ~1K | Instructions |
| Conventions | ~1K | If read |
| **Available for work** | **~135K** | Tool outputs + implementation |

## The Killer: Tool Output

This is where budgets explode:

| Action | Approximate Tokens |
|--------|-------------------|
| Read a 100-line file | ~400 |
| Read a 500-line file | ~2,000 |
| Read a 1000-line file | ~4,000 |
| `ls -la src/` (50 files) | ~500 |
| `npm test` full output | ~5,000-20,000 |
| `git diff` (large change) | ~2,000+ |

**This is why:**
- We use test wrappers (minimal output on pass)
- We search the Pin first (read only relevant files)
- We don't read entire directories
- We exit after one task (before filling the context)

## The Smart Zone vs Dumb Zone

```
Token 0                                              Token 176K
├────────────────────────────────────────────────────────┤
│                                                        │
│  ██████████████████████████████░░░░░░░░░░░░░░░░░░░░░░ │
│  ▲                             ▲                    ▲  │
│  │                             │                    │  │
│  Start                    Performance           Context │
│  (specs loaded)           degrades              full    │
│                           noticeably                    │
│                                                         │
│  ├──── SMART ZONE ────────┤├──── DUMB ZONE ────────┤   │
│                                                         │
```

**In the smart zone:**
- Model remembers objectives
- Follows patterns correctly
- Makes good decisions

**In the dumb zone:**
- Forgets earlier instructions
- Reinvents existing code
- Makes contradictory decisions
- Flails on errors

## Why Ralph Exits After One Task

Traditional approach:
```
[Specs][Task 1][Work][Task 2][Work][Task 3][Work]....[Compaction]...→ DUMB
```

Ralph approach:
```
Loop 1: [Specs][Task 1][Work] → EXIT
Loop 2: [Specs][Task 2][Work] → EXIT  (fresh context!)
Loop 3: [Specs][Task 3][Work] → EXIT  (fresh context!)
```

**Every loop starts fresh. No compaction. Always in smart zone.**

## Practical Tips

### 1. Keep Your Pin Small
```markdown
# BAD: Full specs in README.md (20K tokens)
[entire feature documentation inline]

# GOOD: Index with links (2K tokens)
### Feature X
**Spec:** `specs/features/x.md`
**Code:** `src/x/`
**Keywords:** [list]
```

### 2. Use Test Wrappers
```bash
# BAD: Full test output (10K+ tokens)
npm test

# GOOD: Minimal output (<100 tokens on pass)
./test-wrapper.sh
```

### 3. Read Selectively
```markdown
# BAD: "Read all the source files"
# Results in: 50K tokens of code

# GOOD: "Search specs/README.md, then read only relevant files"
# Results in: 2K tokens of relevant code
```

### 4. Truncate Long Output
```bash
# If you must run a verbose command
some-command 2>&1 | head -50
```

### 5. One Task = One Goal
Don't ask for "implement feature X" (vague, large).
Ask for "create User type in src/types.ts" (specific, small).

## Measuring Your Usage

Want to see how many tokens you're using?

```python
# Using tiktoken (OpenAI's tokenizer, close approximation)
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")
tokens = enc.encode(your_text)
print(f"Tokens: {len(tokens)}")
```

Or online: https://platform.openai.com/tokenizer

## The Mantra

> "Less is more."
> "One goal, one context window."
> "Exit before compaction."
> "Tool output is the killer."
