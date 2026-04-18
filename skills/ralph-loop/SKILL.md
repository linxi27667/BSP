---
name: Ralph循环控制器
description: 启动和管理 Ralph 循环。帮助启动、监控和控制外部 harness，运行多次实现迭代。当用户想运行自主编码循环时使用。
---

# Ralph Loop Skill

## Purpose
Launch and manage the Ralph loop. This skill helps you start, monitor, and control the outer harness that runs repeated implement iterations.

## When to Use
- Ready to start autonomous implementation
- Resuming a paused loop
- Checking loop status
- Learning how to run Ralph

## Philosophy

> "Human ON the loop, not IN the loop"
> "Treat it like a fireplace - watch it, notice patterns, get curious"

The loop skill helps you launch Ralph, but you maintain oversight. Start attended, graduate to unattended.

## Prerequisites

Before running the loop:

1. **Security signed off:** `.ralph-security` exists
2. **Specs exist:** `specs/README.md` has content
3. **Plan exists:** `specs/implementation-plans/active-plan.md` has tasks
4. **Tasks remain:** At least one `- [ ]` in the plan
5. **Scripts ready:** `ralph.sh` and `test-wrapper.sh` are executable

## How to Use

```
User: "Use the ralph/loop skill to start implementation"
```

Or:
```
User: "Use the ralph/loop skill - how do I run this attended?"
```

## Execution Modes

### Mode 1: Attended (Recommended for Starting)

Watch it like a fireplace. Run one iteration, review, continue.

```bash
# Run one iteration manually
cat prompts/implement.md | claude --dangerously-skip-permissions

# Review what happened
git diff HEAD~1
git log -1 --stat

# If good, run another
cat prompts/implement.md | claude --dangerously-skip-permissions

# If bad, reset and adjust
git reset --hard HEAD~1
# Edit specs or prompts
# Try again
```

**Why attended first?**
- Notice patterns in model behavior
- Catch spec errors early
- Build trust before going hands-off
- Learn what works for your project

### Mode 2: Semi-Attended

Let it run, but watch in another terminal.

**Terminal 1 - Run the loop:**
```bash
./ralph.sh
```

**Terminal 2 - Watch:**
```bash
# Watch git activity
watch -n 5 'git log --oneline -10'

# Or watch the log
tail -f .ralph-logs/*.log

# Or watch task progress
watch -n 10 'grep -c "^\- \[ \]" specs/implementation-plans/active-plan.md'
```

**To stop gracefully:**
```bash
touch .ralph-stop
```

### Mode 3: Unattended

Let it run while you do other things.

```bash
# Start in background
nohup ./ralph.sh > ralph-output.log 2>&1 &

# Check on it later
tail -100 ralph-output.log
cat specs/implementation-plans/active-plan.md | grep -c "^\- \[x\]"
```

**Only do this when:**
- You've run attended and trust the setup
- Specs are well-written and reviewed
- Blast radius is acceptable
- You have a way to check in periodically

## Pre-Flight Checks

Before starting the loop, I verify:

### 1. Security
```bash
if [ ! -f ".ralph-security" ]; then
    echo "❌ Security checklist not completed"
    echo "Run: claude 'Use ralph/init skill'"
    exit 1
fi
```

### 2. Implementation Plan
```bash
if [ ! -f "specs/implementation-plans/active-plan.md" ]; then
    echo "❌ No active implementation plan"
    echo "Run: claude 'Use ralph/interview skill'"
    exit 1
fi

TASKS=$(grep -c "^\- \[ \]" specs/implementation-plans/active-plan.md)
if [ "$TASKS" -eq 0 ]; then
    echo "✅ All tasks already complete!"
    exit 0
fi
echo "📋 $TASKS tasks to implement"
```

### 3. Scripts
```bash
if [ ! -x "ralph.sh" ]; then
    echo "❌ ralph.sh not executable"
    echo "Run: chmod +x ralph.sh"
    exit 1
fi
```

### 4. Git Status
```bash
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes detected"
    echo "Consider committing before starting loop"
    git status --short
fi
```

## The Ralph Script Explained

Here's what `ralph.sh` does:

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
    echo "ERROR: Complete security checklist first"
    exit 1
fi

echo "🔄 Starting Ralph loop..."
echo "   Plan: $PLAN"
echo "   Prompt: $PROMPT"
echo "   Stop: touch .ralph-stop"
echo ""

while true; do
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="$LOG_DIR/ralph_$TIMESTAMP.log"
    
    echo "=== Iteration $ITERATION ($TIMESTAMP) ==="
    
    # ┌─────────────────────────────────────────────┐
    # │  INNER HARNESS: Claude does ONE task        │
    # │  Fresh context window every iteration       │
    # └─────────────────────────────────────────────┘
    cat "$PROMPT" | claude --dangerously-skip-permissions 2>&1 | tee "$LOG_FILE"
    
    # ┌─────────────────────────────────────────────┐
    # │  OUTER HARNESS: Deterministic operations    │
    # └─────────────────────────────────────────────┘
    
    # Commit changes (don't rely on model to do this)
    if [ -n "$(git status --porcelain)" ]; then
        git add -A
        git commit -m "ralph: iteration $ITERATION - $(date +%H:%M:%S)"
        git push 2>/dev/null || echo "(push skipped - no remote or auth)"
    else
        echo "No changes detected in iteration $ITERATION"
    fi
    
    # Check remaining tasks
    if [ ! -f "$PLAN" ]; then
        echo "⚠️  Implementation plan not found!"
        break
    fi
    
    REMAINING=$(grep -c "^\- \[ \]" "$PLAN" 2>/dev/null || echo "0")
    COMPLETED=$(grep -c "^\- \[x\]" "$PLAN" 2>/dev/null || echo "0")
    
    echo "📊 Progress: $COMPLETED complete, $REMAINING remaining"
    
    if [ "$REMAINING" -eq 0 ]; then
        echo ""
        echo "🎉 All tasks complete!"
        break
    fi
    
    # Check for manual stop request
    if [ -f ".ralph-stop" ]; then
        echo ""
        echo "🛑 Manual stop requested"
        rm -f .ralph-stop
        break
    fi
    
    # Detect stuck loops (no progress)
    # Could add: if same task is still first [ ] after N iterations, alert
    
    ITERATION=$((ITERATION + 1))
    echo ""
    sleep 2
done

echo ""
echo "════════════════════════════════════════"
echo "Ralph finished after $ITERATION iterations"
echo "Logs: $LOG_DIR/"
echo "════════════════════════════════════════"
```

## Controlling the Loop

### Pause/Stop
```bash
touch .ralph-stop
# Loop will finish current iteration then stop gracefully
```

### Resume
```bash
./ralph.sh
# Picks up where it left off (reads plan, finds first [ ])
```

### Check Progress
```bash
# How many tasks done vs remaining?
echo "Complete: $(grep -c '^\- \[x\]' specs/implementation-plans/active-plan.md)"
echo "Remaining: $(grep -c '^\- \[ \]' specs/implementation-plans/active-plan.md)"
```

### View Logs
```bash
ls -la .ralph-logs/
tail -100 .ralph-logs/ralph_YYYYMMDD_HHMMSS.log
```

### Emergency Stop
```bash
# If loop is stuck, kill it
pkill -f "claude --dangerously"
# Or Ctrl+C if running in foreground
```

## Troubleshooting

### Loop Isn't Making Progress
**Symptoms:** Same task stays as [ ] across multiple iterations

**Causes:**
1. Task is too vague
2. Tests are failing and can't be fixed
3. Missing dependencies

**Fix:**
```bash
touch .ralph-stop  # Stop the loop
# Review the logs
tail -200 .ralph-logs/ralph_*.log | less
# Edit the plan to clarify the task or fix prerequisites
# Resume
./ralph.sh
```

### Model Keeps Reading Too Much
**Symptoms:** Iterations are slow, high token usage

**Fix:** Edit `prompts/implement.md` to be more restrictive:
```markdown
## IMPORTANT
- Read ONLY specs/README.md for context
- Read ONLY the specific files mentioned in the task
- Do NOT read entire directories
```

### Tests Keep Failing
**Symptoms:** Model tries 3 times, gives up, loop continues to next task but eventually all tasks blocked

**Fix:**
```bash
touch .ralph-stop
# Run the failing tests manually
npm test
# Fix the issue manually or update specs
# Resume
./ralph.sh
```

### Wrong Files Being Created
**Symptoms:** Model puts files in wrong locations

**Fix:** Update your Pin with explicit paths:
```markdown
### Feature Name
**Code:** `src/features/name/` (NOT src/name/)
```

And update specs/conventions/code-style.md with directory structure rules.

## Graduation Path

```
Week 1: Fully attended
        - Run one iteration at a time
        - Review every change
        - Build intuition

Week 2: Semi-attended  
        - Run 5-10 iterations
        - Watch in separate terminal
        - Stop if something looks off

Week 3+: Unattended with check-ins
         - Let it run for an hour
         - Review the batch of changes
         - Adjust specs based on patterns

Eventually: Full trust for well-specified tasks
            - Start loop, go do something else
            - Check results when notified complete
```

## Output

When starting the loop, I'll tell you:

```
✅ Pre-flight checks passed

📋 Implementation Plan: specs/implementation-plans/active-plan.md
   - 12 tasks remaining
   - 3 tasks complete

🔐 Security: .ralph-security signed off

Ready to start Ralph loop.

Recommended: Start attended first
   cat prompts/implement.md | claude --dangerously-skip-permissions

Or run the full loop:
   ./ralph.sh

Watch in another terminal:
   tail -f .ralph-logs/*.log

Stop gracefully:
   touch .ralph-stop
```
