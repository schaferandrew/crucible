# Accessibility audit: Conduit web app (summary)

External audit against WCAG 2.2 AA, tested with VoiceOver (macOS Safari), NVDA (Firefox) and keyboard only. Overall result: **fail**. We need to pass before the public-sector contract can be signed.

## Findings

1. **Keyboard users get trapped behind the delete confirmation** (2.1.1 Keyboard, 2.4.3 Focus Order, 2.1.2 No Keyboard Trap, 4.1.2 Name, Role, Value). After choosing "Delete Article", Tab moves through the page *behind* the confirmation, the confirmation's buttons can't be reached or activated from the keyboard, and Escape does nothing. VoiceOver doesn't announce that a confirmation opened at all. When it closes, focus is lost to the top of the page.
2. **"Read more" can't be used without a mouse, and doesn't say what it did** (2.1.1, 4.1.2, 1.3.1). It isn't reachable with Tab. With VoiceOver, activating it gives no indication anything changed, and the newly revealed text isn't read; users have to go back to the start of the article to find it.
3. **The tag filter is mouse-only** (2.1.1, 4.1.2). It can't be opened or used from the keyboard, isn't announced as a menu or list of choices, and gives no indication of which tag is selected.
4. **Some buttons have no name** (4.1.2, 1.1.1). The favorite button is announced as "3, button" with no indication of what it does or whether it's on.
5. **Form errors aren't connected to their fields** (3.3.1 Error Identification, 1.3.1, 4.1.2). In the article editor, an error appears under a field, but screen reader users aren't told the field is invalid and the error isn't read when they move to it.
6. **The "Article published" confirmation is silent** (4.1.3 Status Messages). Sighted users see it; screen reader users get nothing, then the page changes.

## Notes from the auditor

- Prefer native HTML elements and their built-in behavior over recreating them with ARIA. Where a custom widget is genuinely needed, follow the WAI-ARIA Authoring Practices pattern for it.
- Don't fix one finding by breaking another (for example, trapping focus without a way out).
- The design team asked that the visual design stay the same.
