# Verified policy sources and editorial boundaries

Retrieved 2026-11-09. Legal jurisdiction: **BR**. These are general Brazilian
consumer laws, not Olist terms, fictional store policies, or case-specific advice.
English summaries are editorial translations; official Portuguese text controls.
No current merchant SaaS terms are used. No current company consumer terms were
verified, and no historical Olist marketplace policy is claimed.

| Source | Issuing authority | Scope | Verification status |
|---|---|---|---|
| [Consumer Defense Code, Law 8,078/1990](https://www2.camara.leg.br/legin/fed/lei/1990/lei-8078-11-setembro-1990-365086-normaatualizada-pl.pdf) | Brazilian Federal Legislature; law sanctioned by the Presidency | Selected Articles 18, 24, 26, 30, 35, 49, 50 | Selected provisions checked against the Chamber of Deputies consolidated official text. Individual applicability and the version relevant to a historical transaction require review. |
| [Decree 7,962/2013](https://www2.camara.leg.br/legin/fed/decret/2013/decreto-7962-15-marco-2013-775557-publicacaooriginal-139266-pe.html) | Presidency of the Republic | Articles 2, 4, 5, 6, 9 | Official original publication checked; Article 9 specifies effect sixty days after publication. No claim of independently verified subsequent consolidated status. |

The original Planalto URLs are preserved in document metadata. They returned an
access-block page during this audit, so the public Chamber of Deputies copies
above are the retrieved sources. An access block is not evidence about legal status.

Each document stores title, authority, source URL, original source URL, section,
retrieval date, jurisdiction, verification status, content version, language,
translation status, profile and source kind. Metadata is retained in pgvector
and returned in legal citations. Legal ingestion and retrieval reject incomplete
provenance, other jurisdictions and URLs outside the explicitly verified list.

Documents cover return/withdrawal rights, refunds, defects, statutory and
contractual guarantees, delivery obligations, cancellation and electronic
complaint handling. They cannot decide whether an old order qualifies for a
remedy, supply a merchant's refund processing schedule, or prove current
merchant terms. Unsettled individual questions require qualified review; a
demo staff ticket is not contact with a real merchant or an official legal service.

Document bodies contain no customer transactions or reviews. `consumer_policy`
retrieves only `brazil_consumer_law`. General Olist `knowledge_base` retrieval can
also retrieve dataset documentation and labeled demo procedures, with distinct
provenance. Office Store is excluded from both paths.

After explicit approval on 2026-11-09, controlled KB ingestion wrote 15 FastEmbed
chunks across the four profiles, including five legal chunks. The local app now
uses `BAAI/bge-small-en-v1.5` (384 dimensions). All five existing Gemini vectors
were preserved and remain isolated by provider/model filters. Live database
retrieval for the online-return/withdrawal-period question returned Article 49
and the decree with official URLs. Hosted answer generation was not exercised.
Olist transaction migration/import remains pending. See the release runbook.
