# The Fireplace Method

> "Discoveries are found by treating Claude Code as a fireplace. You just sit there and watch it."

## What is the Fireplace Method?

Instead of going fully AFK (away from keyboard), you **watch Ralph work** like you'd watch a campfire:
- Relaxed observation
- Notice patterns
- Get curious about behavior
- Intervene when something seems off

This is "human ON the loop, not IN the loop."

## Why Watch?

### 1. You'll Notice Patterns
After watching a few iterations, you'll see things like:
- "It always forgets to add translations"
- "It reads the same file 3 times"
- "It struggles with this type of test"

These patterns become **tuning opportunities**.

### 2. You'll Catch Spec Errors Early
> "One bad spec = 10,000 lines of garbage"

If your spec has an error, you'll see the model implementing the wrong thing. Catching this in iteration 2 saves 50 iterations of wrong code.

### 3. You'll Build Trust Gradually
You shouldn't trust Ralph with unattended operation until you understand how it behaves on your project. Fireplace mode builds that understanding.

### 4. You'll Find "Golden Windows"
Sometimes the model gets into a perfect state - trajectory is perfect, it's making all the right decisions. You might want to:
- Let it keep going
- Save that context somehow
- Understand what made it work so well

## How to Do It

### Setup: Two Terminals

**Terminal 1 - The Fire:**
```bash
# Run one iteration at a time
cat prompts/implement.md | claude --dangerously-skip-permissions
```

**Terminal 2 - Your Chair:**
```bash
# Watch what's happening
watch -n 5 'git log --oneline -5 && echo "" && git status --short'
```

### The Rhythm

1. **Start an iteration**
   ```bash
   cat prompts/implement.md | claude --dangerously-skip-permissions
   ```

2. **Watch it work**
   - What files is it reading?
   - What's it writing?
   - Does it seem on track?

3. **When it finishes, review**
   ```bash
   git diff HEAD~1     # What changed?
   git log -1          # What did it say it did?
   ```

4. **Decide:**
   - ✅ Good → Run another iteration
   - 🔄 Minor issue → Note it, continue, fix later
   - ❌ Major issue → Reset and adjust
   
   ```bash
   # If bad, reset
   git reset --hard HEAD~1
   # Edit specs or prompt
   # Try again
   ```

5. **Repeat**

### What to Watch For

#### Good Signs 🟢
- Searches the Pin before writing code
- Follows patterns from existing files
- Writes tests
- Marks tasks complete
- Output is focused and relevant

#### Warning Signs 🟡
- Reads lots of files (token budget concern)
- Reinvents something that exists
- Test output is verbose
- Takes multiple attempts to pass tests

#### Bad Signs 🔴
- Creates files in wrong locations
- Ignores existing patterns
- Skips tests
- Doesn't mark task complete
- Goes off-task

### Taking Notes

Keep a scratch file while watching:

```markdown
# Ralph Observations - [Date]

## Iteration 1
- Task: Create user types
- Behavior: Read Pin, found existing pattern, followed it ✅
- Issue: None

## Iteration 2
- Task: Create user repository
- Behavior: Didn't search Pin, reinvented db pattern ⚠️
- Note: Add more keywords for "repository" in Pin

## Iteration 3
- Task: Add validation
- Behavior: Tests failed, fixed on 2nd attempt
- Issue: Test output too verbose, need wrapper
```

These notes become **improvements to your setup**.

## Graduation Path

### Week 1: Pure Fireplace
- Run one iteration
- Review completely
- Decide to continue
- Repeat

**Goal:** Understand behavior, catch spec issues, tune prompt

### Week 2: Batched Fireplace
- Run 3-5 iterations
- Review the batch
- Look for patterns

**Goal:** Build confidence, find systematic issues

### Week 3: Background Fire
- Run `./ralph.sh` in one terminal
- Watch logs/git in another
- Intervene if needed

**Goal:** Semi-autonomous operation with oversight

### Week 4+: Occasional Check-ins
- Start the loop
- Do other work
- Check in every 30-60 minutes
- Review when complete

**Goal:** Trust the system for well-specified tasks

## Common Discoveries from Fireplace Watching

### "It always forgets X"
**Solution:** Add X to the prompt explicitly, or create a post-task evaluation

### "It reads too many files"
**Solution:** Improve Pin keywords so it finds relevant code faster

### "Tests output too much"
**Solution:** Implement test wrapper

### "It puts files in wrong places"
**Solution:** Add explicit paths in implementation plan tasks

### "It reinvents existing code"
**Solution:** Add more keywords to Pin for that feature area

### "It gets stuck on certain test failures"
**Solution:** Cap retries at 3, improve test error output

## The Mindset

**Don't blame the model. Get curious.**

When something goes wrong, ask:
- What did I not specify clearly?
- What pattern did it miss?
- What could I add to the Pin?
- How could the task be more atomic?

The model is a reflection of your setup. Improve the setup, improve the outcomes.

## Quotes to Remember

> "I AFK'd it for 3 months, but I wasn't paying for tokens. I saw it rewrite the lexer and parser so many times. I thought the model was the issue. It wasn't the model." - Jeff

> "You start to notice patterns and you start to anthropomorphize certain tendencies." - Jeff

> "Never blame the model. Always be curious about what's going on." - Jeff

The fireplace reveals all. Watch the fire. 🔥
