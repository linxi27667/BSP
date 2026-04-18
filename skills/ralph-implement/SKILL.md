---
name: Ralph实现器
description: 执行实现计划中的单个任务。Ralph 循环的核心——一个目标，一个上下文窗口，干净退出。当用户需要按步骤逐步执行实现计划时使用。
---

# Ralph Implement Skill

## Purpose
Execute ONE task from the active implementation plan. This is the core of the Ralph loop - one goal, one context window, clean exit.

## When to Use
- Each iteration of the Ralph loop calls this skill
- Manual attended mode (watching like a fireplace)
- Testing before running unattended

## Philosophy

> "Context windows are arrays. The less that window needs to slide, the better."
> "One goal, one objective, one context window."
> "Compaction is the devil."

This skill implements EXACTLY ONE task, then exits. The outer harness (ralph.sh) starts a fresh context window for the next task.

## Token Budget Awareness

**Reality:** ~176K usable tokens (not 200K)

**Budget allocation:**
| Component | Tokens | Notes |
|-----------|--------|-------|
| Specs (Pin) | ~5K | Read once at start |
| Plan | ~2K | Just the checklist |
| This prompt | ~1K | Fixed overhead |
| Tool outputs | VARIABLE | **Minimize this!** |
| Working space | Remainder | For implementation |

**Tool output is the killer.** Don't read entire files if you only need a function. Don't dump full test output.

## How to Use

**Attended (manual):**
```
User: "Use the ralph/implement skill"
```

**Unattended (in loop):**
```bash
# ralph.sh calls this via:
cat prompts/implement.md | claude --dangerously-skip-permissions
```

## Execution Steps

### Step 1: Read the Pin

```
Read: specs/README.md
```

This is the lookup table. Use it to find existing code patterns.

**Do NOT read:**
- Every spec file
- Every source file
- Full directory listings

Just the Pin. It has keywords pointing to what you need.

### Step 2: Read the Implementation Plan

```
Read: specs/implementation-plans/active-plan.md
```

Find the **FIRST** line matching this pattern:
```
- [ ] 
```

That unchecked task is your ONE goal.

**Example:**
```markdown
- [x] Create types in `src/auth/types.ts`        ← Skip (done)
- [x] Create database migration                   ← Skip (done)
- [ ] Create repository in `src/db/auth.ts`      ← THIS IS YOUR TASK
- [ ] Add validation schemas                      ← Ignore (future)
```

### Step 3: Search for Related Code

Before writing anything, search the Pin for related patterns.

**Extract keywords from your task:**
- Task: "Create repository in `src/db/auth.ts`"
- Keywords: repository, database, db, CRUD, model

**Search specs/README.md for these keywords.**

Find entries like:
```markdown
### Database Layer
**Code:** `src/db/`
**Keywords:** repository, CRUD, database, model, query...
```

**Then read the referenced code** to understand patterns:
```
Read: src/db/users.ts (if it exists - as a pattern reference)
```

### Step 4: Read Conventions (If Needed)

```
Read: specs/conventions/code-style.md
```

Only if you need to understand project patterns. Skip if task is simple.

### Step 5: Implement the Task

Now implement your ONE task.

**Guidelines:**
- Follow patterns from existing code you found
- Create files in the correct locations
- Add appropriate types/interfaces
- Handle errors following project patterns

**Token-saving tips:**
- Don't read files you don't need
- Read specific line ranges if possible
- Write code directly, don't draft multiple versions

### Step 6: Write Tests

**Always write tests for new code.**

Check specs/conventions/testing.md for patterns, or follow existing test files.

Place tests appropriately:
- `src/[module]/[module].test.ts` (co-located)
- `tests/[module].test.ts` (separate directory)
- Match existing project convention

### Step 7: Run Tests

**Use the test wrapper for minimal output:**
```bash
./test-wrapper.sh
```

Or if no wrapper exists:
```bash
npm test 2>&1 | head -50
# or
cargo test 2>&1 | head -50
```

**Why head -50?** Full test output can be 10K+ tokens. You only need to see failures.

### Step 8: Handle Test Results

**If tests PASS:**
1. Proceed to Step 9 (mark complete)

**If tests FAIL:**
1. Read the error (it's in the truncated output)
2. Fix the issue
3. Run tests again
4. **Max 3 attempts**

If still failing after 3 attempts:
```
STOP. Leave the task as [ ] (unchecked).
The outer harness will detect no progress and can alert the human.
```

### Step 9: Mark Task Complete

Edit `specs/implementation-plans/active-plan.md`:

**Find your task line:**
```markdown
- [ ] Create repository in `src/db/auth.ts`
```

**Change to:**
```markdown
- [x] Create repository in `src/db/auth.ts`
```

Use str_replace or direct file edit.

### Step 10: Exit

**CRITICAL: STOP HERE.**

Do NOT:
- Continue to the next task
- Start refactoring other code
- Add "nice to have" features
- Keep working in this context window

The outer harness will:
1. Commit your changes
2. Check if tasks remain
3. Start a NEW context window for the next task

**Why exit?** Fresh context = no compaction risk = better outcomes.

## Output Format

End your work with a brief summary:

```
## Task Complete

**Task:** Create repository in `src/db/auth.ts`
**Status:** ✅ Complete
**Files changed:**
- Created: src/db/auth.ts
- Created: src/db/auth.test.ts
**Tests:** Passing

Implementation plan updated. Exiting for fresh context.
```

## Error Handling

### Can't Find Related Code
```
The Pin doesn't have keywords for this task area.
Proceeding with best practices. Consider updating specs/README.md
with more keywords after this task.
```

### Task is Ambiguous
```
Task: "- [ ] Fix the bug"

This task is too vague. Leaving as [ ] for human clarification.
Recommendation: Update the plan with specific task like:
"- [ ] Fix null pointer in src/auth/validate.ts line 45"
```

### Tests Won't Pass After 3 Attempts
```
## Task Incomplete

**Task:** [task description]
**Status:** ❌ Stuck after 3 attempts
**Error:** [brief error description]
**Files changed:** [list]

Leaving task as [ ]. Human review needed.
Possible issues:
- [hypothesis 1]
- [hypothesis 2]
```

### No Implementation Plan Found
```
ERROR: No active implementation plan found.

Expected: specs/implementation-plans/active-plan.md

Run the interview skill first:
claude "Use ralph/interview skill"
```

### All Tasks Already Complete
```
## All Tasks Complete

No unchecked [ ] tasks found in the implementation plan.

Either:
1. The feature is fully implemented 🎉
2. You need to create a new plan with ralph/interview
```

## Anti-Patterns

### Don't Read Everything
```
❌ Read: src/ (entire directory)
✅ Read: specs/README.md → find relevant file → read that file
```

### Don't Do Multiple Tasks
```
❌ "While I'm here, let me also refactor this other file..."
✅ Complete ONE task. Exit. Let next loop handle other work.
```

### Don't Skip Tests
```
❌ "The code looks correct, marking complete"
✅ Write tests. Run tests. Only mark complete if passing.
```

### Don't Fight Failing Tests Forever
```
❌ Attempt 7 of fixing the same error...
✅ Max 3 attempts. Then stop and flag for human review.
```

### Don't Dump Full Output
```
❌ Running npm test (outputs 500 lines)
✅ Running ./test-wrapper.sh OR npm test | head -50
```

## The Mantra

Before starting, remember:
1. **ONE task** - find the first [ ], that's it
2. **Search first** - use the Pin before writing new code
3. **Minimize tokens** - read only what you need
4. **Test always** - no tests = not complete
5. **Exit clean** - mark [x] and stop
