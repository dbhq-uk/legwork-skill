# Grading reports against an answer key

The grader prompts used on 27 and 28 Sep 2026, one per key. Give each to a
fresh agent with the key and the six anonymised reports, and nothing else. The
rules are strict on purpose: the same rules for all six, and every judgement
call written down.

## Common to every key

- Read the whole key, then each report in full. Read nothing else, and do not
  try to work out how a report was produced.
- **Covered** means named with something substantive (a requirement, a price,
  what it sells). A name in a list counts as **mentioned**, separately.
- Rate each covered entity's facts against the key: CORRECT (matches in
  substance), PARTLY (right in part, missing an important condition, or a
  different but defensible reading), WRONG (contradicts the key, or is out of
  date) or UNSTATED.
- Where a report's table and its headline disagree about an entity, mark it
  PARTLY. WRONG is only for a row that is wrong outright.
- **Scope errors** are entities the key excludes, presented as in scope. An
  excluded entity the report describes correctly is a **correct exclusion**. One
  listed only as unconfirmed, with its cells unknown or under limitations, is
  neither.
- **Other errors** are any other claim the key directly contradicts, each quoted
  briefly.
- Write the scores as JSON keyed by report label, with a one-line verdict per
  report, and reply with a compact table.

## banks

Question: "which UK banks publish a public API sandbox, and what does each
require before you can call it?" Read the key's scope rule and its scoring
note on Open Banking Directory enrolment. Table 1 holds the in-scope banks,
marked core or extra; Table 2 holds the banks checked and excluded. Score core
recall (of 16), extra recall, requirement accuracy per covered Table 1 bank,
scope errors, correct exclusions and other errors.

## postgres

Question: "compare the pricing of the main hosted Postgres providers for a
small UK startup, and tell me which to pick." Read the core/extra list, the
price table, the notes on disagreements (AWS free tier, the DigitalOcean
price, the Google Iowa rates) and the facts a correct recommendation should
rest on.

Score:
- core recall (of 9) and extra recall
- the free tier and the cheapest production tier per covered provider:
  separately, then overall, where WRONG in either makes the whole WRONG
- UK region availability
- whether the report claims UK GDPR requires UK hosting (it does not, so that
  claim is an error)
- the recommendation as SOUND, WEAK or UNSOUND: SOUND means a pick the key
  defends, resting on no fact the key contradicts, and dealing with UK location
- other errors.

Allow for the currency and region differences the key itself notes.

## campervan

Question: "which UK suppliers sell flat-pack campervan furniture kits for a
Ford Transit L3H2, and what does a complete kit cost?" The key's central
finding is that no UK supplier sells a complete flat-pack kit listed for the
L3H2: the one complete Transit kit is listed for the L3H3. Score core recall
(of 3), extra recall, price and fit accuracy per covered supplier, the central
finding (YES, PARTLY, or NO for a report that names a "complete L3H2 kit" at a
price), scope errors (Transit Custom only, pre-built, fitted conversions, not
UK), correct exclusions and other errors.
