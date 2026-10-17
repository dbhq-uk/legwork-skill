# 2026-10-17 - wide search: live check

**What:** one real `search.py` call with the real keys on this machine
(Bright Data, Exa, TypeSafe), then `--more` against its record, then the same
angle with a bad Exa key. Plan Task 9. Run at 18:10 UTC on 17 Oct 2026, at
commit `5183017`.

## 1. The call

```bash
python3 scripts/search.py \
  --angle "which UK banks publish a public API sandbox, and what does each require before you can call it?" \
  --wording "UK bank API sandbox developer portal" \
  --wording "open banking sandbox register developer UK" \
  --wording "bank developer portal sandbox credentials free sign up" \
  --wording "UK bank API sandbox requires Open Banking Directory enrolment" \
  --wording "bank sandbox API not available to individual developers UK" \
  --wording "fintech developer review UK bank sandbox" \
  --out-dir /tmp/legwork-live
```

Exit 0. The status line:

```
search: 6 wordings · google 6/6 ok · exa ok · jev on · 58 leads (top 40 shown) · 59s
```

- **Leads:** 58, 40 printed, then a `+18 more` line naming the record.
- **Time:** 58.7 seconds of network, inside the 110-second default.
- **Google:** 9 results for each wording. Each wording took 7.0 to 58.4
  seconds; the two slowest set the wall time.
- **Exa:** 8 citations in 2.3 seconds. Its reported cost was $0.005. Exa's
  answer printed last, under its UNVERIFIED heading.
- **Exa only:** all 8 of Exa's leads were found by no Google wording, and all
  8 are banks' own developer or TPP pages: Santander, Coventry Building
  Society, the Co-operative Bank, Chase UK, Lloyds (two pages), First Bank of
  Nigeria UK and AIB GB.
- **Jev:** on. It lifted five of those Exa-only pages into the top ten, each
  with a Jev score of 0.61 to 0.72 against a reciprocal-rank score half that
  of a lead two Google lists shared.

## 2. `--more`

`search.py --more <record> --from 41` printed leads 41 to 58 of 58 from the
record and exited 0, with no network call.

## 3. A provider failing

The same angle with two wordings and `EXA_API_KEY=invalid` exited 0:

```
search: 2 wordings · google 2/2 ok · exa: failed (HTTP 401: {"requestId":"...","error":"Invalid API key. Provide a valid key using 'Authoriza) · jev on · 18 leads · 63s
```

Google was unaffected: 9 results for each wording, 18 leads.

## 4. What looked wrong

- **Bright Data's latency varies widely.** The same wording took 58.4
  seconds in the first call and 63.1 in the third. 63.1 is over the
  60-second timeout for one attempt, so the first attempt most likely timed
  out and the retry answered in about 3 seconds [inferring from the
  timings: the record keeps one `seconds` for the wording, not one per
  attempt]. One slow wording sets the wall time of the whole call.
- **The Exa error reason is cut at 120 characters mid-word.** That is the
  designed limit; nothing in it is a key.

Nothing else looked wrong.
