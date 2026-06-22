# [PROJECT NAME] Specifications Index

> **Purpose:** Lookup table for Ralph. Rich keywords improve search hits = less reinvention.
> **Updated:** [DATE]

---

## How to Use This Document

When implementing ANY feature with Ralph:
1. **Search this document FIRST** using keywords from your task
2. Find relevant existing specs and code
3. Follow established patterns
4. Do NOT reinvent existing functionality

---

## Core Systems

### [System 1 Name]
**Spec:** `specs/features/[name].md`
**Code:** `src/[path]/`
**Keywords:** [primary-term], [synonym1], [synonym2], [related-concept],
[action-verb1], [action-verb2], [domain-term], [alternative-phrasing],
[related-feature], [common-abbreviation]
**Status:** [Planning | In Progress | Complete | Deprecated]

### [System 2 Name]
**Spec:** `specs/features/[name].md`
**Code:** `src/[path]/`
**Keywords:** [15-30 relevant terms covering synonyms, related concepts,
action verbs, domain terminology, and alternative phrasings]
**Status:** [status]

---

## Feature Modules

### [Feature Name]
**Spec:** `specs/features/[feature].md`
**Plan:** `specs/implementation-plans/[feature]-plan.md`
**Code:** `src/[feature]/`
**Keywords:** [comprehensive keyword list]
**Status:** [Planning | In Progress | Complete]
**Dependencies:** [what this requires]
**Dependents:** [what requires this]

---

## Conventions & Patterns

### Code Style
**Location:** `specs/conventions/code-style.md`
**Keywords:** formatting, naming, structure, organization, linting,
code style, conventions, standards

### Testing Patterns
**Location:** `specs/conventions/testing.md`
**Keywords:** unit test, integration test, property test, mock,
fixture, assertion, coverage, TDD, test, spec, jest, vitest

### Error Handling
**Location:** `specs/conventions/errors.md`
**Keywords:** exception, error, failure, recovery, logging,
try catch, error handling, validation, error boundary

---

## External Integrations

### [Integration Name]
**Spec:** `specs/integrations/[name].md`
**Code:** `src/integrations/[name]/`
**Keywords:** [API name], [service name], [related terms]
**Docs:** [URL to external API docs]

---

## Keyword Guidelines

When adding entries, include:
1. **Primary terms:** The obvious name
2. **Synonyms:** Alternative words (auth = authentication = login)
3. **Related concepts:** Things used together
4. **Action verbs:** create, update, delete, validate, fetch
5. **Domain language:** Industry-specific terms
6. **Abbreviations:** Common short forms (db = database)
7. **Alternative phrasings:** How else might someone describe this?

**Goal:** 15-30 keywords per feature for maximum search hits.
