"""Reading an existing fetch log back, so a re-run does not start from zero.

A deep run that dies at minute 30 has already paid for every retrieval in the
log. These tests pin the summary that lets the next run skip them.
"""

import sources


def row(url, angle='an angle', quote='', status='ok'):
    return {'url': url, 'angle': angle, 'quote': quote, 'status': status, 'kind': 'press'}


def test_resume_state_of_an_absent_log_is_empty_not_an_error():
    state = sources.resume_state([])
    assert state['sources'] == 0
    assert state['angles'] == {}
    assert state['fetched'] == []


def test_angles_are_counted_so_an_uncovered_sub_question_is_visible():
    rows = [
        row('https://a.example/1', angle='what does the incumbent charge'),
        row('https://b.example/2', angle='what does the incumbent charge'),
        row('https://c.example/3', angle='what do buyers say they pay'),
    ]
    state = sources.resume_state(rows)
    assert state['angles'] == {
        'what does the incumbent charge': 2,
        'what do buyers say they pay': 1,
    }


def test_fetched_urls_come_back_canonicalised_so_a_refetch_is_recognised():
    """The point of the list is to answer 'have I already opened this'. It has to
    match the same page reached with tracking parameters or a trailing slash."""
    rows = [row('https://www.a.example/page/?utm_source=x')]
    state = sources.resume_state(rows)
    assert state['fetched'] == ['https://a.example/page']


def test_a_failed_retrieval_is_not_reported_as_already_fetched():
    rows = [
        row('https://ok.example/1', status='ok'),
        row('https://blocked.example/2', status='blocked'),
    ]
    state = sources.resume_state(rows)
    assert state['fetched'] == ['https://ok.example/1']
    assert state['failed'] == ['https://blocked.example/2']


def test_sources_still_missing_a_quote_are_listed_because_the_gate_needs_them():
    rows = [
        row('https://a.example/1', quote='Something quotable.'),
        row('https://b.example/2', quote=''),
    ]
    state = sources.resume_state(rows)
    assert state['quoted'] == 1
    assert state['unquoted'] == ['https://b.example/2']


def test_duplicate_retrievals_of_one_page_are_reported_once():
    rows = [
        row('https://a.example/1'),
        row('https://a.example/1/'),
    ]
    state = sources.resume_state(rows)
    assert state['fetched'] == ['https://a.example/1']
    assert state['sources'] == 2
