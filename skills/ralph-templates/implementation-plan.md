# Implementation Plan: [Feature Name]

> **Created:** [DATE]
> **Status:** [Not Started | In Progress | Complete]
> **Estimated:** ~[N] Ralph iterations

## Overview

[One paragraph describing what this plan implements and why]

## Prerequisites

- [ ] [Any setup or dependencies that must exist first]
- [ ] [Required specs to be reviewed]

---

## Tasks

### Phase 1: [Phase Name, e.g., "Data Model"]

- [ ] [Action verb] [specific thing] in `path/to/file.ts`
      - [Brief detail of what to do]
      - Pattern: see `path/to/similar.ts`

- [ ] [Action verb] [specific thing] in `path/to/file.ts`
      - [Brief detail]

### Phase 2: [Phase Name, e.g., "Core Logic"]

- [ ] [Action verb] [specific thing] in `path/to/file.ts`
      - [Brief detail]
      - Error handling: follow `src/utils/errors.ts`

- [ ] [Action verb] [specific thing] in `path/to/file.ts`
      - [Brief detail]

### Phase 3: [Phase Name, e.g., "API Layer"]

- [ ] [Action verb] [specific thing] in `path/to/file.ts`
      - [Brief detail]

- [ ] [Action verb] [specific thing] in `path/to/file.ts`
      - [Brief detail]

### Phase 4: [Phase Name, e.g., "Integration"]

- [ ] Connect [new feature] to [existing system]
      - Update `path/to/existing.ts`
      - [Integration details]

### Phase 5: Testing

- [ ] Write unit tests for `src/[feature]/[main].ts`
- [ ] Write unit tests for `src/[feature]/[other].ts`
- [ ] Write integration tests for [API/feature]
- [ ] Verify all existing tests still pass

### Phase 6: Documentation

- [ ] Add JSDoc comments to public functions
- [ ] Update specs/README.md (change status to Complete)
- [ ] [Any other documentation]

---

## Implementation Notes

### Patterns to Follow
- [Pattern 1]: See `path/to/example.ts`
- [Pattern 2]: See `path/to/example.ts`

### Utilities to Use
- Error handling: `src/utils/errors.ts`
- Validation: `src/utils/validation.ts`
- [Other utilities]

### Gotchas
- [Known issue or thing to watch out for]
- [Another gotcha]

---

## Task Guidelines

Each task should be:
- **Atomic:** One focused change
- **Specific:** Name exact files
- **Testable:** Clear when it's done
- **Independent:** Minimal dependencies on other uncompleted tasks

**Bad task:** "Implement authentication"
**Good task:** "Create User interface in `src/auth/types.ts` with id, email, passwordHash fields"
