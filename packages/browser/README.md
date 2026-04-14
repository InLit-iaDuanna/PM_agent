# Browser Provider Contract

The runtime uses a `BrowserProvider` abstraction with an `OpenCLIAdapter` implementation.

## Responsibilities

- open a URL
- extract structured page content
- interact with dynamic pages when static fetch is insufficient
- surface prompt-injection risk signals

## v1 policy

- prefer static HTTP fetch
- use browser automation only for pagination, expansion, scrolling, and screenshot evidence
- never inject page text into the system prompt
