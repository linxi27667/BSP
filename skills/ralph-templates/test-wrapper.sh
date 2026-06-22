#!/bin/bash
# Test Wrapper - Minimal output to save tokens
#
# Most test runners dump thousands of tokens.
# Ralph only needs to know: pass or fail + error details.
#
# Usage: ./test-wrapper.sh
#
# Customize TEST_COMMAND for your project:
#   npm test | cargo test | pytest | go test ./... | etc.

# ══════════════════════════════════════════════════════════════
# Configuration - EDIT THIS FOR YOUR PROJECT
# ══════════════════════════════════════════════════════════════

TEST_COMMAND="${TEST_COMMAND:-npm test}"

# ══════════════════════════════════════════════════════════════
# Run Tests
# ══════════════════════════════════════════════════════════════

echo "Running: $TEST_COMMAND"
echo ""

# Capture output
RESULT=$($TEST_COMMAND 2>&1)
EXIT_CODE=$?

# ══════════════════════════════════════════════════════════════
# Output - Minimal tokens
# ══════════════════════════════════════════════════════════════

if [ $EXIT_CODE -eq 0 ]; then
    # ✅ PASS - Minimal output (save tokens!)
    echo "════════════════════════════════════════"
    echo "✓ All tests passed"
    echo "════════════════════════════════════════"
else
    # ❌ FAIL - Show only relevant error info
    echo "════════════════════════════════════════"
    echo "✗ Tests failed (exit code: $EXIT_CODE)"
    echo "════════════════════════════════════════"
    echo ""
    
    # Extract just the failing test info
    # This grep pattern catches most test frameworks
    echo "$RESULT" | grep -E -A 15 \
        "FAIL|FAILED|Error:|error:|ERROR|AssertionError|expect\(|assert|panic|CRASHED" \
        | head -50
    
    echo ""
    echo "════════════════════════════════════════"
    echo "(Output truncated to save tokens)"
    echo "════════════════════════════════════════"
fi

exit $EXIT_CODE

# ══════════════════════════════════════════════════════════════
# Customization Examples
# ══════════════════════════════════════════════════════════════
#
# Node.js / npm:
#   TEST_COMMAND="npm test"
#
# Node.js / yarn:
#   TEST_COMMAND="yarn test"
#
# Rust:
#   TEST_COMMAND="cargo test"
#
# Python / pytest:
#   TEST_COMMAND="pytest -v"
#
# Go:
#   TEST_COMMAND="go test ./..."
#
# Ruby / RSpec:
#   TEST_COMMAND="bundle exec rspec"
#
# Java / Maven:
#   TEST_COMMAND="mvn test"
#
# Java / Gradle:
#   TEST_COMMAND="./gradlew test"
#
# ══════════════════════════════════════════════════════════════
