# Curation Taxonomy

Use this taxonomy for editorial curation, topic packs, and article briefs.

## Source Type

- `paper`
- `review`
- `guideline`
- `policy_statement`
- `regulator`
- `clinical_trial`
- `product`
- `company`
- `society`
- `university`
- `book`
- `author_profile`
- `clinic`
- `blog`
- `news`
- `market_context`
- `other`
- `UNKNOWN`

## Trust Grade

- `S`: regulator, official guideline, clinical trial registry, major systematic review, high-quality official source
- `A`: peer-reviewed paper, official society page, university source, textbook metadata from durable source
- `B`: company evidence page, reputable news, professional organization context
- `C`: clinic or marketing page, blog with named author, secondary summary
- `D`: weak blog, unverifiable marketing, thin repost
- `UNKNOWN`: insufficient metadata

Trust grade is not claim truth. A high-trust source can still contain a claim that needs fact verification.

## Evidence Role

- `clinical_evidence`
- `guideline`
- `policy`
- `regulatory`
- `product_marketing`
- `market_context`
- `textbook_context`
- `historical_context`
- `biographical_context`
- `review`
- `critique`
- `controversy`
- `other`
- `UNKNOWN`

## Editorial Bucket

- `core_evidence`: useful for the central argument
- `official_boundary`: official guidance, policy, contraindication, scope boundary
- `product_landscape`: product/company/product-evidence context
- `market_landscape`: clinics, associations, local market language
- `controversy_balance`: skeptical/supportive conflict sources
- `background_context`: textbook, author, history, school of thought
- `quote_candidate`: source has a short phrase worth later checking
- `fact_check_only`: do not publish from it yet, but use as claim seed
- `reject`: not useful, duplicate, inaccessible, or too weak

## Article Usefulness

- `high`: can anchor a section after fact verification
- `medium`: useful support or context
- `low`: background only
- `reject`: do not use

## Readiness

- `ready_for_brief`: source pack can support an article brief
- `needs_fact_verification`: claims must be verified before briefing
- `background_only`: useful context but not an article anchor
- `reject`: exclude from publication workflow

## Claim Audit Verdict

- `SUPPORTED`: cited source directly supports the claim.
- `PARTIALLY_SUPPORTED`: source supports part of the claim, but the public wording needs a caveat.
- `UNSUPPORTED`: cited source does not support the claim.
- `CONFLICT`: cited or related sources disagree.
- `UNKNOWN`: source is missing, inaccessible, ambiguous, or too thin to decide.

## Hallucination Risk Flags

- `invented_source`
- `unsupported_claim`
- `citation_mismatch`
- `overclaim`
- `source_blending`
- `confidence_overstatement`
- `missing_caveat`
- `access_limited`
- `stale_information`
- `translation_or_terminology_risk`

## Public Use

- `usable`: can be used in an article after normal editorial review.
- `usable_with_caveat`: can be used only with the stated caveat.
- `do_not_use`: do not use in public writing unless separately re-verified.

## Common Topic Pack Families

For vision therapy runs, common packs include:

- `amblyopia`
- `binocular-vision`
- `convergence-insufficiency`
- `strabismus`
- `diplopia`
- `accommodative-oculomotor`
- `post-concussion-vision`
- `digital-therapeutics`
- `guidelines-societies`
- `korea-market-regulation`
- `reading-dyslexia-controversy`
- `textbooks-people-schools`

For other domains, workers should create domain-specific slugs with lowercase letters, digits, and hyphens.
