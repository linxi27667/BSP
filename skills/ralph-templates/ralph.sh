#!/bin/bash
# Ralph Loop - Outer Harness
# 
# This script runs the Ralph implementation loop.
# Each iteration: fresh Claude context → one task → commit → repeat
#
# Usage: ./ralph.sh
# Stop:  touch .ralph-stop

set -e

# Configuration
PLAN="specs/implementation-plans/active-plan.md"
PROMPT="prompts/implement.md"
LOG_DIR=".ralph-logs"
MAX_ITERATIONS="${RALPH_MAX_ITERATIONS:-100}"
SLEEP_BETWEEN="${RALPH_SLEEP:-2}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[Ralph]${NC} $1"; }
log_success() { echo -e "${GREEN}[Ralph]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[Ralph]${NC} $1"; }
log_error() { echo -e "${RED}[Ralph]${NC} $1"; }

# Setup
mkdir -p "$LOG_DIR"
ITERATION=0

# ══════════════════════════════════════════════════════════════
# Pre-flight Checks
# ══════════════════════════════════════════════════════════════

log_info "Running pre-flight checks..."

# Security
if [ ! -f ".ralph-security" ]; then
    log_error "Security checklist not completed!"
    echo "Run: claude 'Use ralph/init skill'"
    exit 1
fi

# Implementation plan
if [ ! -f "$PLAN" ]; then
    log_error "No implementation plan found at $PLAN"
    echo "Run: claude 'Use ralph/interview skill'"
    exit 1
fi

# Prompt file
if [ ! -f "$PROMPT" ]; then
    log_error "No prompt file found at $PROMPT"
    echo "Run: claude 'Use ralph/init skill'"
    exit 1
fi

# Count tasks
REMAINING=$(grep -c "^\- \[ \]" "$PLAN" 2>/dev/null || echo "0")
COMPLETED=$(grep -c "^\- \[x\]" "$PLAN" 2>/dev/null || echo "0")

if [ "$REMAINING" -eq 0 ]; then
    log_success "All tasks already complete! Nothing to do."
    exit 0
fi

# ══════════════════════════════════════════════════════════════
# Start Loop
# ══════════════════════════════════════════════════════════════

echo ""
echo "════════════════════════════════════════════════════════════"
log_info "Starting Ralph loop"
echo "════════════════════════════════════════════════════════════"
echo ""
log_info "Plan: $PLAN"
log_info "Tasks: $COMPLETED complete, $REMAINING remaining"
log_info "Max iterations: $MAX_ITERATIONS"
log_info "Stop gracefully: touch .ralph-stop"
echo ""

while [ "$ITERATION" -lt "$MAX_ITERATIONS" ]; do
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="$LOG_DIR/ralph_${TIMESTAMP}.log"
    
    echo "────────────────────────────────────────────────────────────"
    log_info "Iteration $ITERATION - $(date +%H:%M:%S)"
    echo "────────────────────────────────────────────────────────────"
    
    # ┌─────────────────────────────────────────────────────────────┐
    # │  INNER HARNESS: Claude executes ONE task                    │
    # │  Fresh context window = no compaction risk                  │
    # └─────────────────────────────────────────────────────────────┘
    
    if ! cat "$PROMPT" | claude --dangerously-skip-permissions 2>&1 | tee "$LOG_FILE"; then
        log_warn "Claude exited with error (may be normal)"
    fi
    
    # ┌─────────────────────────────────────────────────────────────┐
    # │  OUTER HARNESS: Deterministic operations                    │
    # │  Don't rely on model for git - do it here                   │
    # └─────────────────────────────────────────────────────────────┘
    
    # Commit any changes
    if [ -n "$(git status --porcelain)" ]; then
        log_info "Committing changes..."
        git add -A
        git commit -m "ralph: iteration $ITERATION - $(date +%H:%M:%S)"
        
        # Push if remote exists (ignore errors)
        if git push 2>/dev/null; then
            log_info "Pushed to remote"
        fi
    else
        log_warn "No changes in iteration $ITERATION"
    fi
    
    # Check remaining tasks
    REMAINING=$(grep -c "^\- \[ \]" "$PLAN" 2>/dev/null || echo "0")
    COMPLETED=$(grep -c "^\- \[x\]" "$PLAN" 2>/dev/null || echo "0")
    
    log_info "Progress: $COMPLETED complete, $REMAINING remaining"
    
    # All done?
    if [ "$REMAINING" -eq 0 ]; then
        echo ""
        log_success "🎉 All tasks complete!"
        break
    fi
    
    # Manual stop requested?
    if [ -f ".ralph-stop" ]; then
        echo ""
        log_warn "🛑 Manual stop requested"
        rm -f .ralph-stop
        break
    fi
    
    ITERATION=$((ITERATION + 1))
    
    # Cool-down between iterations
    sleep "$SLEEP_BETWEEN"
    echo ""
done

# ══════════════════════════════════════════════════════════════
# Finish
# ══════════════════════════════════════════════════════════════

echo ""
echo "════════════════════════════════════════════════════════════"
log_info "Ralph finished"
echo "════════════════════════════════════════════════════════════"
echo ""
log_info "Iterations: $ITERATION"
log_info "Tasks completed: $COMPLETED"
log_info "Tasks remaining: $REMAINING"
log_info "Logs: $LOG_DIR/"
echo ""

if [ "$REMAINING" -gt 0 ]; then
    log_warn "Some tasks remain. Review logs and plan, then restart."
fi
