status: draft
updated: 2026-05-24

# Casting an ad-hoc prompt without a ritual file

## Running a one-shot prompt

As a developer, I want to cast a free-text prompt directly without authoring a ritual file, so that quick agent queries don't require boilerplate.

- when the name I supply doesn't match any registered ritual, the whole input is treated as a coding prompt
- the response streams as it would for any other coding call
- approvals work the same way as for a scripted ritual

## Predictable dispatch when ritual names exist

As a developer, I want registered rituals to take precedence over the free-text fallback, so that an existing ritual name is never accidentally shadowed by a prompt.

- a name that matches a ritual runs the ritual
- a name that matches no ritual falls back to the prompt
- the implicit one-shot ritual doesn't show up in ritual listings

## Discovering both forms

As a developer, I want the cast command's help to document both the named and free-text forms, so that I know both invocations are supported.
