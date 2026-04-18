---
name: Ralph初始化器
description: 在新项目或现有项目中引导 Ralph 循环结构。当用户想为项目设置 Ralph 自主编码循环时使用。
---

# Ralph Init Skill

## Purpose
Bootstrap the Ralph loop structure in a new or existing project.

## When to Use
- Starting a new project that will use Ralph loops
- Adding Ralph to an existing project
- After cloning a repo that needs Ralph setup

## What This Skill Does

1. **Creates directory structure:**
   ```
   specs/
   ├── README.md              # The Pin (lookup table)
   ├── current-state.md       # Document what exists
   ├── features/              # Feature specifications
   ├── implementation-plans/  # Task checklists
   └── conventions/           # Code style guides
   prompts/
   └── implement.md           # Implementation prompt
   ```

2. **Installs scripts:**
   - `ralph.sh` - The outer harness loop runner
   - `test-wrapper.sh` - Minimal test output wrapper

3. **Runs security checklist:**
   - Asks about infrastructure (local vs ephemeral VM)
   - Documents blast radius
   - Creates `.ralph-security` sign-off

4. **Detects existing code:**
   - Scans for existing source files
   - Pre-populates the Pin with discovered features
   - Asks clarifying questions about the codebase

## How to Use

```
User: "Use the ralph/init skill to set up Ralph in this project"
```

## Execution Steps

### Step 1: Security Pre-Flight

Before creating anything, I must verify the environment is safe for autonomous operation.

**Ask the user:**

1. "Where is this running?"
   - Local laptop (DANGEROUS - will warn heavily)
   - Remote VM / Cloud instance (better)
   - Ephemeral / disposable environment (ideal)

2. "What credentials exist on this machine?"
   - List all API keys, auth tokens, SSH keys
   - Document the blast radius if compromised

3. "Is there private/sensitive data accessible?"
   - Personal files, wallets, auth cookies
   - Production credentials or data

**If local laptop with real credentials:**
```
⚠️  WARNING: Running Ralph with --dangerously-skip-permissions on a local 
machine with real credentials is risky. If the model is compromised or 
makes a mistake, it could:
- Steal authentication cookies
- Access private keys/wallets  
- Pivot to other systems

Recommendation: Use an ephemeral VM with only the credentials needed.

Do you want to continue anyway? (yes/no)
```

### Step 2: Create Directory Structure

```bash
mkdir -p specs/{features,implementation-plans,conventions}
mkdir -p prompts
```

### Step 3: Detect Existing Codebase

Scan the project to understand what exists:

```bash
# Find source directories
find . -type f -name "*.ts" -o -name "*.js" -o -name "*.py" -o -name "*.rs" -o -name "*.go" | head -50

# Find existing README or docs
find . -name "README*" -o -name "*.md" | head -20

# Find package files
ls package.json Cargo.toml pyproject.toml go.mod 2>/dev/null
```

**Ask the user:**
- "I found [X]. Can you give me a quick overview of what this project does?"
- "What are the main features/modules?"
- "What's the test command?" (npm test, cargo test, pytest, etc.)

### Step 4: Create the Pin (specs/README.md)

Based on discovery, create the lookup table:

```markdown
# [Project Name] Specifications Index

> This is the lookup table for Ralph. Rich keywords improve search hits.

## How to Use
When implementing features, ALWAYS search this document first.
Find relevant existing code before writing new code.

---

## Core Systems

### [Discovered Module 1]
**Code:** `src/[path]/`
**Keywords:** [generate 15-30 relevant terms]
**Status:** Existing

### [Discovered Module 2]
**Code:** `src/[path]/`  
**Keywords:** [generate 15-30 relevant terms]
**Status:** Existing

---

## Conventions
**Code Style:** `specs/conventions/code-style.md`
**Testing:** `specs/conventions/testing.md`
```

### Step 5: Create Current State Doc

```markdown
# Current State

## Overview
[Based on user description]

## Existing Features
| Feature | Status | Location |
|---------|--------|----------|
| [Feature 1] | ✅ Exists | `src/...` |

## Tech Stack
- Language: [detected]
- Framework: [detected]
- Test runner: [user provided]

## Test Command
`[user provided test command]`
```

### Step 6: Create Implementation Prompt

Create `prompts/implement.md` with the project's test command:

```markdown
## Context
Study: specs/README.md

## Task
1. Read `specs/implementation-plans/active-plan.md`
2. Find FIRST unchecked `- [ ]` task
3. Implement ONLY that task

## Execution
1. Search specs/README.md for related code
2. Implement following specs/conventions/
3. Write tests
4. Run: `[TEST_COMMAND]`

## On Success
1. Change task from `- [ ]` to `- [x]` in the plan
2. STOP

## On Failure  
1. Fix and retry (max 3 attempts)
2. If still failing, STOP and leave as `- [ ]`

## CRITICAL
- ONE task only
- Do NOT continue to next task
- Exit cleanly for fresh context
```

### Step 7: Create Test Wrapper

Create `test-wrapper.sh`:

```bash
#!/bin/bash
# Minimal test output to save tokens

RESULT=$([TEST_COMMAND] 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ All tests passed"
else
    echo "✗ Tests failed:"
    echo "$RESULT" | grep -A 10 "FAIL\|Error\|error:\|FAILED" | head -30
fi

exit $EXIT_CODE
```

### Step 8: Create Ralph Loop Script

Create `ralph.sh`:

```bash
#!/bin/bash
set -e

PLAN="specs/implementation-plans/active-plan.md"
PROMPT="prompts/implement.md"
LOG_DIR=".ralph-logs"
ITERATION=0

mkdir -p "$LOG_DIR"

# Security check
if [ ! -f ".ralph-security" ]; then
    echo "ERROR: Complete security checklist first (run ralph/init)"
    exit 1
fi

echo "🔄 Starting Ralph loop..."

while true; do
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    echo ""
    echo "=== Iteration $ITERATION ($TIMESTAMP) ==="
    
    # Inner harness - Claude does ONE task
    cat "$PROMPT" | claude --dangerously-skip-permissions 2>&1 | tee "$LOG_DIR/ralph_$TIMESTAMP.log"
    
    # Outer harness - deterministic git
    if [ -n "$(git status --porcelain)" ]; then
        git add -A
        git commit -m "ralph: iteration $ITERATION"
        git push 2>/dev/null || true
    fi
    
    # Check remaining tasks
    if [ ! -f "$PLAN" ]; then
        echo "⚠️  No implementation plan found"
        break
    fi
    
    REMAINING=$(grep -c "^\- \[ \]" "$PLAN" 2>/dev/null || echo "0")
    
    if [ "$REMAINING" -eq 0 ]; then
        echo ""
        echo "✅ All tasks complete!"
        break
    fi
    
    echo "📋 $REMAINING tasks remaining"
    
    # Check for manual stop
    if [ -f ".ralph-stop" ]; then
        echo "🛑 Manual stop requested"
        rm -f .ralph-stop
        break
    fi
    
    ITERATION=$((ITERATION + 1))
    sleep 2
done

echo ""
echo "Ralph finished after $ITERATION iterations"
echo "Logs: $LOG_DIR/"
```

### Step 9: Create Security Sign-Off

Create `.ralph-security`:

```markdown
# Ralph Security Sign-Off

## Environment
- Type: [local/remote/ephemeral]
- Machine: [description]

## Credentials Present
- [List all credentials]

## Blast Radius
If compromised, worst case is:
- [Document impact]

## Sign-Off
- [x] I understand the risks
- [x] Blast radius is acceptable
- [x] Environment is appropriate

Signed: [user]
Date: [date]
```

### Step 10: Update .gitignore

```bash
echo "" >> .gitignore
echo "# Ralph" >> .gitignore
echo ".ralph-logs/" >> .gitignore
echo ".ralph-stop" >> .gitignore
echo ".ralph-state" >> .gitignore
```

### Step 11: Make Scripts Executable

```bash
chmod +x ralph.sh test-wrapper.sh
```

## Output Summary

After completion, tell the user:

```
✅ Ralph initialized!

Created:
- specs/README.md (the Pin - edit to add keywords)
- specs/current-state.md (document what exists)
- specs/conventions/ (add your code style guides)
- prompts/implement.md (the loop prompt)
- ralph.sh (the loop runner)
- test-wrapper.sh (minimal test output)
- .ralph-security (signed off)

Next steps:
1. Review and enhance specs/README.md with more keywords
2. Run: claude "Use ralph/interview skill" to create feature specs
3. Review the generated implementation plan
4. Run: ./ralph.sh (or attended: manually run implement skill)

Tip: Start attended (watch it like a fireplace) before going unattended.
```
