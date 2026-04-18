---
name: Ralph需求访谈
description: 通过引导式对话生成需求规格说明。一个坏的需求=10000行垃圾代码。当用户想定义功能需求、编写规格文档或进行需求澄清时使用。
---

# Ralph Interview Skill

## Purpose
Generate feature specifications through guided conversation. This is the most important skill - **one bad spec = 10,000 lines of garbage code**.

## When to Use
- Adding a new feature to the project
- Starting work on a new module
- Refining an existing feature specification
- Before any Ralph implementation loop

## Philosophy

> "I don't create my specs. I generate them. Then I review them and edit them by hand. Then I let it rip with Ralph." - Jeff Huntley

You don't write specs from scratch. You have a conversation, generate a draft, review it carefully, then let Ralph implement it.

## What This Skill Does

1. **Conducts a structured interview** about what you want to build
2. **Generates a feature specification** based on your answers
3. **Creates an implementation plan** with atomic tasks
4. **Updates the Pin** (specs/README.md) with the new feature

## How to Use

```
User: "Use the ralph/interview skill - I want to add user authentication"
```

Then answer the questions. When satisfied, say "generate" or "done".

## Execution Steps

### Step 1: Load Context

First, read the existing project context:

```
Read: specs/README.md (understand existing features)
Read: specs/current-state.md (understand current capabilities)
Read: specs/conventions/ (understand patterns)
```

### Step 2: Conduct the Interview

**IMPORTANT:** Ask questions, don't assume. This is a conversation, not a monologue.

#### Round 1: Problem Discovery
Ask ONE question at a time:

- "What problem are you trying to solve?"
- "Who experiences this problem?"
- "What happens if we don't solve it?"

Wait for answers before continuing.

#### Round 2: Solution Exploration
- "What's your proposed solution?"
- "What alternatives did you consider?"
- "What's the MVP version vs the full vision?"

#### Round 3: Integration Analysis
- "Looking at specs/README.md, I see you have [X, Y, Z]. How does this new feature interact with those?"
- "What existing code can we reuse?"
- "What new data structures are needed?"

#### Round 4: Technical Requirements
- "Any performance requirements?"
- "Security implications?"
- "Error handling needs?"

#### Round 5: Scope Definition
- "What's explicitly OUT of scope for now?"
- "Any constraints I should know about?"
- "Dependencies on other work?"

### Step 3: Summarize Understanding

Before generating, summarize:

```
"Let me make sure I understand:

You want to build [FEATURE] which will:
- [Capability 1]
- [Capability 2]

It will integrate with [EXISTING SYSTEMS] by [HOW].

MVP scope includes: [X, Y, Z]
Out of scope for now: [A, B, C]

Does this match your intent?"
```

**Wait for confirmation before proceeding.**

### Step 4: Generate the Feature Spec

Create `specs/features/[feature-name].md`:

```markdown
# Feature: [Name]

## Overview
[2-3 sentence summary]

## Problem Statement
[What problem this solves, who has it]

## Solution
[Proposed solution approach]

## Requirements

### Functional
- [ ] [Requirement 1]
- [ ] [Requirement 2]
- [ ] [Requirement 3]

### Non-Functional
- Performance: [requirements]
- Security: [requirements]
- Error handling: [requirements]

## Integration Points

### [Existing System 1]
- How it integrates: [description]
- Files affected: `path/to/files`

### [Existing System 2]
- How it integrates: [description]
- Files affected: `path/to/files`

## Data Model

### [New Type/Model 1]
```typescript
interface Example {
  id: string;
  // ...
}
```

## API Design (if applicable)

### [Endpoint 1]
- Method: POST
- Path: /api/[path]
- Request: [schema]
- Response: [schema]

## Out of Scope
- [Explicit exclusion 1]
- [Explicit exclusion 2]

## Open Questions
- [Any unresolved items]

## Dependencies
- Requires: [what must exist first]
- Blocks: [what this unblocks]
```

### Step 5: Generate the Implementation Plan

Create `specs/implementation-plans/[feature-name]-plan.md`:

**CRITICAL:** Tasks must be ATOMIC. One task = one focused change.

```markdown
# Implementation Plan: [Feature Name]

## Overview
[One paragraph summary]

## Prerequisites
- [ ] [Any setup needed first]

---

## Tasks

### Phase 1: Data Model
- [ ] Create types in `src/[feature]/types.ts`
      - Define [Type1], [Type2]
      - Export from index
- [ ] Create database migration `src/db/migrations/XXX_[feature].sql`
      - Table: [table_name]
      - Columns: [list]
- [ ] Create repository `src/db/[feature].ts`
      - CRUD operations
      - Follow patterns in `src/db/users.ts`

### Phase 2: Core Logic  
- [ ] Create `src/[feature]/[feature].ts`
      - Implement [function1]
      - Follow error patterns from `src/utils/errors.ts`
- [ ] Create `src/[feature]/validation.ts`
      - Schema for [input validation]

### Phase 3: API Layer
- [ ] Create route `src/routes/[feature].ts`
      - POST /api/[feature]
      - GET /api/[feature]/:id
- [ ] Add validation middleware
- [ ] Register in `src/routes/index.ts`

### Phase 4: Integration
- [ ] Connect to [existing system]
      - Update `src/[existing]/index.ts`
- [ ] Update [affected component]

### Phase 5: Testing
- [ ] Unit tests for `src/[feature]/[feature].ts`
- [ ] Unit tests for `src/[feature]/validation.ts`
- [ ] Integration tests for API routes
- [ ] Verify existing tests still pass

### Phase 6: Documentation
- [ ] Add JSDoc comments to public functions
- [ ] Update specs/README.md status to "Complete"

---

## Notes for Implementation
- Follow patterns in: `src/[similar-feature]/`
- Use existing utilities: `src/utils/[relevant].ts`
- Error handling: Use `AppError` class from `src/utils/errors.ts`

## Estimated Iterations
~[X] Ralph loops (1 task per loop)
```

### Step 6: Update the Pin

Add entry to `specs/README.md`:

```markdown
### [Feature Name]
**Spec:** `specs/features/[feature-name].md`
**Plan:** `specs/implementation-plans/[feature-name]-plan.md`
**Code:** `src/[feature]/` (planned)
**Keywords:** [word1], [word2], [word3], [word4], [word5],
[synonym1], [synonym2], [related1], [related2], [action1],
[action2], [domain-term1], [domain-term2], [alternative-phrasing1],
[concept1], [concept2]
**Status:** Planning
**Dependencies:** [list]
```

**Keyword generation:** Include 15-30 terms:
- Primary name and synonyms
- Related concepts
- Action verbs (create, delete, update, validate, etc.)
- Domain-specific terminology
- Alternative phrasings users might search

### Step 7: Activate the Plan (Optional)

Ask the user:

```
"The implementation plan is ready. Would you like me to:

A) Set this as the active plan (copy to active-plan.md)
B) Leave it for manual activation later

If you have an existing active plan in progress, choose B."
```

If A:
```bash
cp specs/implementation-plans/[feature]-plan.md specs/implementation-plans/active-plan.md
```

### Step 8: Output Summary

```
✅ Specification generated!

Created:
- specs/features/[feature-name].md (the specification)
- specs/implementation-plans/[feature-name]-plan.md (the task list)
- Updated specs/README.md (added to Pin)

⚠️  IMPORTANT: Review these files before running Ralph!
One bad spec = 10,000 lines of garbage.

Check:
- [ ] Does the spec match your intent?
- [ ] Are the tasks atomic enough? (one thing per checkbox)
- [ ] Are file paths correct?
- [ ] Are dependencies listed?

Next steps:
1. Review and edit the generated specs
2. Activate: cp specs/implementation-plans/[feature]-plan.md specs/implementation-plans/active-plan.md
3. Run: ./ralph.sh (or attended mode first)
```

## Anti-Patterns to Avoid

### Don't Assume
```
❌ "I'll assume you want JWT authentication"
✅ "What authentication method do you want? (JWT, session, OAuth, etc.)"
```

### Don't Bundle Tasks
```
❌ "- [ ] Create user model, validation, and API routes"
✅ "- [ ] Create user model in src/models/user.ts"
   "- [ ] Create validation schema in src/validation/user.ts"  
   "- [ ] Create API routes in src/routes/user.ts"
```

### Don't Skip Integration Questions
```
❌ "I'll create a new auth system"
✅ "I see you have src/middleware/session.ts - should this integrate with that or replace it?"
```

### Don't Forget Keywords
```
❌ "Keywords: auth"
✅ "Keywords: authentication, login, logout, session, JWT, token, 
    password, credentials, user identity, sign in, sign out, 
    authorization, permissions, access control, security"
```
