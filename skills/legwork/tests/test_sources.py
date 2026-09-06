"""Fitness scoring, claim-aware recency, and the fetch log."""

import json
from datetime import datetime, timedelta, timezone

import pytest

import sources


NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Dates. The predecessor compared an aware datetime against a naive
# datetime.now(), raised TypeError, and swallowed it - so every timezone-carrying
# date silently scored as unknown age. These pin that it cannot come back.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value', [
    '2026-07-01',
    '2026-07-01T00:00:00Z',
    '2026-07-01T00:00:00+00:00',
    '2026-07-01T02:00:00+02:00',
])
def test_timezone_forms_all_parse_to_the_same_instant_class(value):
    parsed, reason = sources.parse_date(value)
    assert reason is None
    assert parsed.tzinfo is not None
    assert parsed.date().isoformat() == '2026-07-01'


@pytest.mark.parametrize('value', [
    '2026-07-01',
    '2026-07-01T00:00:00Z',
    '2026-07-01T00:00:00+00:00',
])
def test_recency_is_identical_whether_or_not_a_timezone_is_present(value):
    multiplier, age, note = sources.recency_multiplier(value, 'price', now=NOW)
    assert note is None
    assert age == pytest.approx(27.5, abs=1)
    assert multiplier > 0.9


def test_unparseable_date_reports_a_reason_rather_than_silently_scoring_neutral():
    multiplier, age, note = sources.recency_multiplier('last Tuesday', 'price', now=NOW)
    assert age is None
    assert note and 'unparseable' in note
    assert multiplier == sources.RECENCY_UNKNOWN


def test_missing_date_is_reported_not_assumed():
    _, _, note = sources.recency_multiplier(None, 'price', now=NOW)
    assert note == 'no date supplied'


def test_future_date_is_flagged():
    ahead = (NOW + timedelta(days=30)).isoformat()
    _, _, note = sources.recency_multiplier(ahead, 'price', now=NOW)
    assert note == 'date is in the future'


# ---------------------------------------------------------------------------
# Fitness is per claim, not per domain
# ---------------------------------------------------------------------------

def test_the_same_page_is_primary_for_one_claim_and_worthless_for_another():
    """A pricing page proves what something costs. It says nothing about whether
    anyone likes it, and scoring it as if it did is the failure mode a domain
    allowlist cannot avoid."""
    assert sources.tier_for('vendor_pricing', 'price') == 'primary'
    assert sources.tier_for('vendor_pricing', 'sentiment') == 'unrated'
    assert (sources.fitness('vendor_pricing', 'price', '2026-07-01', now=NOW)['score']
            > sources.fitness('vendor_pricing', 'sentiment', '2026-07-01', now=NOW)['score'])


def test_a_forum_thread_beats_a_vendor_page_on_sentiment():
    thread = sources.fitness('community', 'sentiment', '2026-07-01', now=NOW)
    vendor = sources.fitness('vendor_marketing', 'sentiment', '2026-07-01', now=NOW)
    assert thread['score'] > vendor['score']


def test_a_filing_beats_an_analyst_on_market_size():
    filing = sources.fitness('filing', 'market', '2026-07-01', now=NOW)
    analyst = sources.fitness('analyst', 'market', '2026-07-01', now=NOW)
    assert filing['tier'] == 'primary' and analyst['tier'] == 'secondary'
    assert filing['score'] > analyst['score']


def test_an_unrated_source_kind_is_flagged_rather_than_scored_as_if_understood():
    result = sources.fitness('search_data', 'price', '2026-07-01', now=NOW)
    assert result['tier'] == 'unrated'
    assert any('not rated' in note for note in result['notes'])


# ---------------------------------------------------------------------------
# Recency decays at a rate set by the claim
# ---------------------------------------------------------------------------

def test_a_stale_price_decays_far_faster_than_a_stale_market_figure():
    old = (NOW - timedelta(days=730)).isoformat()
    price = sources.recency_multiplier(old, 'price', now=NOW)[0]
    market = sources.recency_multiplier(old, 'market', now=NOW)[0]
    assert price < market


def test_an_old_primary_source_still_outranks_a_fresh_blog():
    old_primary = sources.fitness('vendor_pricing', 'price', (NOW - timedelta(days=900)).isoformat(), now=NOW)
    fresh_blog = sources.fitness('blog', 'price', NOW.isoformat(), now=NOW)
    assert old_primary['score'] > fresh_blog['score']


# ---------------------------------------------------------------------------
# Numeric tokens
# ---------------------------------------------------------------------------

def test_numbers_are_normalised_so_the_same_figure_compares_equal():
    assert sources.extract_numbers('revenue was 1,600 last year') == ['1600']
    assert sources.extract_numbers('a 96% share') == ['96']
    assert sources.extract_numbers('worth 2.4 billion') == ['2.4']


def test_number_extraction_is_capped():
    text = ' '.join(str(n) for n in range(1000))
    assert len(sources.extract_numbers(text, limit=50)) == 50


# ---------------------------------------------------------------------------
# Source-kind inference stays conservative
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('url,expected', [
    ('https://acme.example/pricing', 'vendor_pricing'),
    ('https://learn.microsoft.com/en-us/graph/api/overview', 'vendor_docs'),
    ('https://www.reddit.com/r/accounting/comments/abc/thread/', 'community'),
    ('https://find-and-update.company-information.service.gov.uk/company/06839674', 'filing'),
    ('https://github.com/dbhq-uk/legwork-skill', 'registry'),
])
def test_recognised_shapes_are_inferred(url, expected):
    assert sources.infer_source_kind(url) == expected


def test_an_unrecognised_url_returns_unknown_rather_than_a_plausible_guess():
    assert sources.infer_source_kind('https://some-company.example/thoughts/2026/piece') == 'unknown'


# ---------------------------------------------------------------------------
# Fetch log round trip
# ---------------------------------------------------------------------------

def test_log_round_trip_preserves_angle_and_numbers(tmp_path):
    path = str(tmp_path / 'run.tsv')
    sources.append_row(path, {
        'url': 'https://acme.example/pricing', 'kind': 'vendor_pricing',
        'angle': 'what does it cost', 'via': 'webfetch',
        'fetched_at': '2026-07-28T09:00:00+00:00', 'status': 'ok',
        'date': '2026-07-01', 'numbers': '30,12', 'title': 'Pricing',
    })
    rows = sources.read_rows(path)
    assert len(rows) == 1
    assert rows[0]['angle'] == 'what does it cost'
    assert rows[0]['numbers'] == ['30', '12']


def test_reading_an_absent_log_is_not_an_error(tmp_path):
    assert sources.read_rows(str(tmp_path / 'nothing.tsv')) == []


def test_tabs_and_newlines_in_a_title_cannot_corrupt_the_log(tmp_path):
    path = str(tmp_path / 'run.tsv')
    sources.append_row(path, {'url': 'https://a.example/', 'kind': 'blog', 'angle': 'x',
                              'via': 'websearch', 'title': 'a\ttitle\nwith control chars'})
    rows = sources.read_rows(path)
    assert len(rows) == 1
    assert rows[0]['title'] == 'a title with control chars'


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

def test_a_quote_survives_the_log_round_trip(tmp_path):
    path = str(tmp_path / 'run.tsv')
    sources.append_row(path, {
        'url': 'https://a.example/docs', 'kind': 'vendor_docs', 'angle': 'x',
        'via': 'webfetch', 'quote': 'Publishing to the catalogue is not supported.',
    })
    assert sources.read_rows(path)[0]['quote'] == 'Publishing to the catalogue is not supported.'


def test_a_log_written_before_quotes_existed_still_parses(tmp_path):
    """The column is appended last precisely so old logs keep working."""
    path = tmp_path / 'old.tsv'
    path.write_text(
        'url\tkind\tangle\tvia\tfetched_at\tstatus\tdate\tnumbers\ttitle\n'
        'https://a.example/\tblog\tan angle\twebsearch\t2026-07-28T09:00:00+00:00\tok\t\t30\tA title\n',
        encoding='utf-8')
    row = sources.read_rows(str(path))[0]
    assert row['numbers'] == ['30']
    assert row.get('quote', '') == ''


# ---------------------------------------------------------------------------
# The query column, the direct transport, and self-verification
#
# Measured on 2026-09-06 across seven fetch logs, 215 rows: the numbers column
# was filled on one row, because WebFetch returns a model summary rather than
# page text and there was nothing to pass to --text-file. The figure-tracing
# gate was therefore proved by fixtures and dead in production. These pin the
# two ways it comes back to life - page text when there is any, the verbatim
# quote when there is not - and the record of what was asked.
# ---------------------------------------------------------------------------

def test_the_query_round_trips_through_the_log(tmp_path):
    path = str(tmp_path / 'run.tsv')
    sources.append_row(path, {
        'url': 'https://a.example/pricing', 'kind': 'vendor_pricing', 'angle': 'what it costs',
        'via': 'direct', 'quote': 'Team plan: 30 US dollars per user per month.',
        'query': 'site:a.example pricing',
    })
    assert sources.read_rows(path)[0]['query'] == 'site:a.example pricing'


def test_a_log_written_before_the_query_column_still_parses(tmp_path):
    path = tmp_path / 'old.tsv'
    path.write_text(
        'url\tkind\tangle\tvia\tfetched_at\tstatus\tdate\tnumbers\ttitle\tquote\n'
        'https://a.example/\tblog\tan angle\twebsearch\t2026-07-28T09:00:00+00:00\tok\t\t30\tA title\tA sentence.\n',
        encoding='utf-8')
    row = sources.read_rows(str(path))[0]
    assert row['quote'] == 'A sentence.'
    assert row.get('query', '') == ''


def test_direct_is_a_transport_the_log_accepts():
    assert 'direct' in sources.VIA_VALUES


def test_numbers_are_taken_from_the_quote_when_there_is_no_page_text():
    """Half of runs never produce a text file. The quote is verbatim page text."""
    numbers, origin = sources.numbers_for_row(
        explicit='', page_text=None, quote='Team plan: 30 US dollars per user per month.')
    assert numbers == ['30']
    assert origin == 'quote'


def test_page_text_beats_the_quote_when_both_are_present():
    numbers, origin = sources.numbers_for_row(
        explicit='', page_text='The page mentions 30 and 1,600 and 12.5.',
        quote='Team plan: 30 US dollars.')
    assert origin == 'text'
    assert '1600' in numbers and '12.5' in numbers


def test_an_explicit_numbers_flag_wins_over_both():
    numbers, origin = sources.numbers_for_row(
        explicit='30,44', page_text='999', quote='888')
    assert numbers == ['30', '44']
    assert origin == 'flag'


def test_no_numbers_anywhere_is_reported_as_none():
    assert sources.numbers_for_row(explicit='', page_text=None, quote='No figures here.') == ([], 'none')


def test_a_quote_taken_from_the_page_verifies():
    page = 'Nav Home About\n\nTeam plan: 30 US dollars per user per month, billed annually.\n'
    assert sources.quote_appears_in('Team plan: 30 US dollars per user per month, billed annually.', page)


def test_verification_survives_whitespace_and_curly_punctuation():
    page = 'The vendor’s  own\npage says  the plan is “best value” – for teams.'
    assert sources.quote_appears_in("The vendor's own page says the plan is \"best value\" - for teams.", page)


def test_a_quote_that_is_not_on_the_page_fails_verification():
    assert not sources.quote_appears_in('Team plan: 40 US dollars.', 'Team plan: 30 US dollars.')


def test_an_empty_quote_does_not_count_as_verified():
    assert not sources.quote_appears_in('', 'anything at all')


# ---------------------------------------------------------------------------
# The retrieval receipt
# ---------------------------------------------------------------------------

RECEIPT_ROWS = [
    {'url': 'https://a.example/1', 'via': 'direct', 'status': 'ok', 'query': 'q1'},
    {'url': 'https://a.example/2', 'via': 'webfetch', 'status': 'ok', 'query': 'q1'},
    {'url': 'https://b.example/3', 'via': 'websearch', 'status': 'ok', 'query': 'q2'},
    {'url': 'https://c.example/4', 'via': 'brightdata', 'status': 'ok', 'query': 'q2'},
    {'url': 'https://d.example/5', 'via': 'api', 'status': 'ok', 'query': ''},
    {'url': 'https://e.example/6', 'via': 'direct', 'status': 'blocked', 'query': 'q3'},
]


def test_the_receipt_separates_opened_from_snippet_only():
    receipt = sources.retrieval_receipt(RECEIPT_ROWS)
    assert receipt['sources'] == 6
    assert receipt['opened'] == 4       # direct, webfetch, brightdata, api
    assert receipt['snippet_only'] == 1  # the websearch row
    assert receipt['brightdata'] == 1
    assert receipt['blocked'] == 1
    assert receipt['queries'] == 3


def test_a_blocked_row_is_not_counted_as_opened():
    receipt = sources.retrieval_receipt(
        [{'url': 'https://a.example/1', 'via': 'direct', 'status': 'blocked'}])
    assert receipt['opened'] == 0 and receipt['blocked'] == 1


def test_the_same_page_opened_twice_counts_once():
    rows = [{'url': 'https://a.example/x', 'via': 'direct', 'status': 'ok'},
            {'url': 'https://a.example/x?utm_source=z', 'via': 'webfetch', 'status': 'ok'}]
    assert sources.retrieval_receipt(rows)['opened'] == 1


def test_the_receipt_line_reads_as_a_receipt():
    assert sources.receipt_line(sources.retrieval_receipt(RECEIPT_ROWS)) == (
        '6 sources · 4 opened · 1 snippet-only · 1 via Bright Data · 1 blocked · 3 queries')


# ---------------------------------------------------------------------------
# --from-fetch: the sidecar fetch.py writes becomes the log row, so the URL,
# title, date and page text cannot drift between opening a page and recording it
# ---------------------------------------------------------------------------

def _sidecar(tmp_path, **overrides):
    text_file = tmp_path / 'page.txt'
    text_file.write_text('Team plan: 30 US dollars per user per month, billed annually.\n',
                         encoding='utf-8')
    payload = {'url': 'https://acme.example/pricing', 'title': 'Acme pricing',
               'date': '2026-07-01', 'text_file': str(text_file), 'verdict': 'ok'}
    payload.update(overrides)
    path = tmp_path / 'page.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return str(path)


def test_from_fetch_fills_the_row_from_the_sidecar(tmp_path, capsys):
    tsv = str(tmp_path / 'run.tsv')
    sources.main_with_args([
        'log', '--tsv', tsv, '--from-fetch', _sidecar(tmp_path),
        '--angle', 'what it costs', '--kind', 'vendor_pricing',
        '--quote', 'Team plan: 30 US dollars per user per month, billed annually.',
        '--query', 'site:acme.example pricing'])
    result = json.loads(capsys.readouterr().out)
    assert result['quote_verified'] is True
    assert result['numbers_from'] == 'text'
    row = sources.read_rows(tsv)[0]
    assert row['url'] == 'https://acme.example/pricing'
    assert row['title'] == 'Acme pricing'
    assert row['date'] == '2026-07-01'
    assert row['via'] == 'direct'
    assert '30' in row['numbers']


def test_explicit_flags_beat_the_sidecar(tmp_path, capsys):
    tsv = str(tmp_path / 'run.tsv')
    sources.main_with_args([
        'log', '--tsv', tsv, '--from-fetch', _sidecar(tmp_path),
        '--angle', 'a', '--kind', 'vendor_pricing', '--via', 'brightdata',
        '--date', '2026-08-08', '--title', 'Mine'])
    row = sources.read_rows(tsv)[0]
    assert row['via'] == 'brightdata' and row['date'] == '2026-08-08' and row['title'] == 'Mine'


def test_a_blocked_sidecar_logs_the_failure_rather_than_a_source(tmp_path, capsys):
    tsv = str(tmp_path / 'run.tsv')
    sources.main_with_args([
        'log', '--tsv', tsv, '--angle', 'a', '--kind', 'vendor_docs',
        '--from-fetch', _sidecar(tmp_path, verdict='blocked', text_file='')])
    row = sources.read_rows(tsv)[0]
    assert row['status'] == 'blocked'
    assert sources.retrieval_receipt(sources.read_rows(tsv))['blocked'] == 1


def test_a_quote_the_page_does_not_carry_is_reported(tmp_path, capsys):
    tsv = str(tmp_path / 'run.tsv')
    sources.main_with_args([
        'log', '--tsv', tsv, '--from-fetch', _sidecar(tmp_path),
        '--angle', 'a', '--kind', 'vendor_pricing',
        '--quote', 'Team plan: 40 US dollars per user per month.'])
    captured = capsys.readouterr()
    assert json.loads(captured.out)['quote_verified'] is False
    assert 'not found in the page text' in captured.err
