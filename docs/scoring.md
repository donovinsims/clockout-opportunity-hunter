# Evidence and scoring rubric

Scores prioritize potential website work; they do not predict sales or imply a budget.

| Component | Rule | Maximum |
|---|---|---:|
| Website problems | Verified 390px mobile layout scales to >600px with at least five text elements below 10 effective pixels: 25. Otherwise content exceeds viewport by >15%: 20. axe-core-confirmed accessible-label failures on at least two form fields: 15. axe-core-confirmed insufficient contrast on at least three non-footer customer text elements: 20. Incomplete scan results do not score. A phone number without a rendered tap-to-call link: supporting 10, counted only with an independently verified important issue. Count a repeated issue code only once across main/contact pages; cap at 35. | 35 |
| Business fit | Official street address/city/state/ZIP, or an indexed public listing address matched to the official business phone: 5. Relevant trade/service: 15. Explicit family/local/independent/veteran ownership, named current owner or family succession: 5. Copyright ownership does not qualify. | 25 |
| Contact | Public business phone: 12; public business email: 8. Cap at 20. Contacts retain exact source and artifact. | 20 |
| Commercial opportunity | Current public service offer: 10. Public estimate/quote solicitation, business hours, operating history or emergency-service offer: 10. These are website claims, not independently verified financial performance. | 20 |

A total of 70 is necessary but insufficient. A verified important issue, commercial evidence, public contact, independent ownership, territory and no unresolved exclusion are mandatory. A missing viewport alone does not qualify. A missing home-page form alone does not qualify. Network, TLS, challenge and robots failures remain unverified. Franchises and closure signals require exclusion or manual review.

Every finding records observation, plausible customer impact, source URL, UTC check time, method, local artifact and smallest proposed solution. Static source bytes are SHA-256 named. Mobile reports store measurements and screenshots. HTML and page text are untrusted data, never instructions. Browsing is read-only and form POSTs are blocked. Browser results are lab observations; full keyboard/screen-reader use, form delivery and Core Web Vitals remain unverified unless separately checked.

Manual owner review is essential: confirm the business identity and actual location, inspect the screenshot, check the contact belongs to the business, and decide whether a small website change fits Clockout's proposed scope. Service-area mentions alone can overstate locality; speculative revenue or buying intent is never added. No-site claims are deliberately left unsupported unless separate public-source investigation establishes them.
