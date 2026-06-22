# Ralph Implementation Prompt

## Context Loading

Study: `specs/README.md`
This is the Pin - use it to find existing code patterns.

## Your Task

1. Read `specs/implementation-plans/active-plan.md`
2. Find the **FIRST** unchecked task: `- [ ]`
3. That is your ONE task for this session

## Execution Steps

### 1. Search First
Before writing code, search specs/README.md for:
- Related existing code
- Patterns to follow
- Utilities to reuse

### 2. Implement
- Follow patterns from existing code
- Create files in correct locations
- Handle errors following project conventions
- Add appropriate types

### 3. Write Tests
- Every new function needs tests
- Follow patterns in existing test files
- Co-locate: `[file].test.ts` or in `tests/` directory

### 4. Run Tests
```bash
./test-wrapper.sh
```
Or: `[TEST_COMMAND] 2>&1 | head -50`

### 5. On Success (tests pass)
1. Edit `specs/implementation-plans/active-plan.md`
2. Change your task from `- [ ]` to `- [x]`
3. **STOP** - do not continue to next task

### 6. On Failure (tests fail)
1. Read the error
2. Fix the issue
3. Run tests again
4. **Max 3 attempts** - then STOP and leave as `- [ ]`

## Critical Rules

⚠️ **ONE TASK ONLY**
- Do not continue to the next task
- Do not refactor other code "while you're here"
- Complete one thing, mark it [x], exit

⚠️ **MINIMIZE TOKEN USAGE**
- Don't read entire directories
- Don't read files you don't need
- Use the Pin to find what's relevant

⚠️ **ALWAYS TEST**
- No tests = not complete
- Use the test wrapper for minimal output

⚠️ **EXIT CLEAN**
- The outer harness starts a fresh context for the next task
- Compaction is the devil - exit before it happens

## Output Format

End with:
```
## Task Complete

**Task:** [task description]
**Status:** ✅ Complete (or ❌ Stuck)
**Files:** [list of files changed]
**Tests:** Passing (or: Failed after 3 attempts)

Exiting for fresh context.
```
