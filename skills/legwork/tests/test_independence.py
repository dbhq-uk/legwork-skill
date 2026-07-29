"""Independence grouping and angle-aware corroboration."""

import pytest

import independence


def row(url, angle='an angle', title='', kind='press'):
    return {'url': url, 'angle': angle, 'title': title, 'kind': kind, 'status': 'ok'}


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('https://www.example.com/page/', 'https://example.com/page'),
    ('https://example.com/page?utm_source=x&id=7', 'https://example.com/page?id=7'),
    ('https://example.com/page#section', 'https://example.com/page'),
    ('HTTPS://Example.COM/Page', 'https://example.com/Page'),
    ('https://example.com/page?fbclid=abc', 'https://example.com/page'),
])
def test_canonicalisation(raw, expected):
    assert independence.canonicalize(raw) == expected


def test_query_order_does_not_change_identity():
    assert (independence.canonicalize('https://e.com/p?b=2&a=1')
            == independence.canonicalize('https://e.com/p?a=1&b=2'))


# ---------------------------------------------------------------------------
# Registrable domain
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('host,expected', [
    ('learn.microsoft.com', 'microsoft.com'),
    ('microsoft.com', 'microsoft.com'),
    ('www.bbc.co.uk', 'bbc.co.uk'),
    ('news.bbc.co.uk', 'bbc.co.uk'),
    ('find-and-update.company-information.service.gov.uk', 'service.gov.uk'),
    ('example.com', 'example.com'),
])
def test_registrable_domain(host, expected):
    assert independence.registrable_domain(host) == expected


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def test_one_vendors_many_pages_are_one_voice():
    """The real pattern: 26 of 78 bibliography entries on learn.microsoft.com."""
    rows = [
        row('https://learn.microsoft.com/graph/api/a', title='Graph API A'),
        row('https://learn.microsoft.com/graph/api/b', title='Graph API B'),
        row('https://support.microsoft.com/kb/1', title='Known issue'),
        row('https://techcommunity.microsoft.com/post/2', title='Community post'),
    ]
    groups = independence.group_sources(rows)
    assert len(groups) == 1
    assert 'same party' in groups[0]['reason']


def test_syndication_collapses_to_one_group():
    headline = 'Regulator opens consultation on record keeping for small firms'
    rows = [
        row('https://outlet-a.example/1', title=headline),
        row('https://outlet-b.example/2', title=headline + ' today'),
        row('https://outlet-c.example/3', title='Regulator opens consultation on record keeping, small firms'),
    ]
    groups = independence.group_sources(rows)
    assert len(groups) == 1
    assert 'same origin' in groups[0]['reason']


def test_the_same_page_reached_twice_is_one_source():
    rows = [
        row('https://example.com/page', title='A'),
        row('https://www.example.com/page/?utm_source=news', title='A'),
    ]
    assert len(independence.group_sources(rows)) == 1


def test_genuinely_different_sources_stay_separate():
    rows = [
        row('https://one.example/a', title='Quarterly filings point to consolidation'),
        row('https://two.example/b', title='Why practitioners are leaving spreadsheets'),
        row('https://three.example/c', title='The hidden cost of manual triage'),
    ]
    assert len(independence.group_sources(rows)) == 3


# ---------------------------------------------------------------------------
# Corroboration counts on the layer the pipeline does not amplify
# ---------------------------------------------------------------------------

def test_two_independent_groups_from_two_angles_corroborate():
    rows = [
        row('https://acme.example/pricing', angle='what does it cost', title='Pricing'),
        row('https://forum.example/t/1', angle='what do buyers pay', title='What we actually pay'),
    ]
    assert independence.corroboration(rows)['corroboration'] == 2


def test_five_distinct_publishers_from_one_angle_count_as_one_confirmation():
    """The never-binds guard, at unit level.

    A gate that counted independence groups would read this as five
    confirmations. Every one of them was surfaced by the same query, so they are
    five reports of one line of enquiry.
    """
    titles = [
        'Quarterly filings point to consolidation',
        'Why practitioners are leaving spreadsheets behind',
        'A regulator opens consultation on record keeping',
        'Small firms report rising software spend',
        'The hidden cost of manual triage in professional services',
    ]
    rows = [row('https://outlet{}.example/story'.format(i), angle='one query', title=title)
            for i, title in enumerate(titles)]
    result = independence.corroboration(rows)
    assert result['groups'] == 5, 'the sources really are distinct parties'
    assert result['angles'] == 1
    assert result['corroboration'] == 1, 'but one angle can only confirm once'


def test_corroboration_never_exceeds_the_number_of_angles():
    rows = [row('https://o{}.example/p'.format(i), angle='angle {}'.format(i % 2),
                title='Distinct headline number {}'.format(i)) for i in range(8)]
    result = independence.corroboration(rows)
    assert result['corroboration'] <= result['angles'] == 2


def test_corroboration_never_exceeds_the_number_of_groups():
    rows = [row('https://acme.example/p{}'.format(i), angle='angle {}'.format(i),
                title='Page {}'.format(i)) for i in range(6)]
    result = independence.corroboration(rows)
    assert result['groups'] == 1
    assert result['corroboration'] == 1


def test_an_unlabelled_log_degrades_to_plain_group_counting():
    rows = [row('https://one.example/a', angle='', title='Filings point to consolidation'),
            row('https://two.example/b', angle='', title='Practitioners leaving spreadsheets')]
    assert independence.corroboration(rows)['corroboration'] == 2


def test_no_sources_is_no_corroboration():
    assert independence.corroboration([])['corroboration'] == 0


# ---------------------------------------------------------------------------
# The amplifier test: drive the fan-out and assert the gate still binds
# ---------------------------------------------------------------------------

def test_the_gate_still_binds_when_the_fan_out_is_actually_running():
    """A unit test that feeds the gate its parameters cannot catch a never-binds
    design. This one simulates Gather doing what Gather does - taking a single
    sub-question and expanding it into many sources across many parties - and
    asserts corroboration does not inflate with the fan-out.
    """
    subjects = ['consolidation among small firms', 'spreadsheet migration costs',
                'regulatory consultation timing', 'software spend per seat',
                'manual triage hours lost', 'partner succession planning',
                'audit sampling practice', 'client onboarding friction',
                'payroll bureau margins', 'cloud ledger adoption',
                'insolvency caseload trends', 'apprenticeship recruitment',
                'practice management churn', 'VAT filing error rates',
                'advisory revenue mix', 'benchmarking data quality',
                'furlough scheme legacy', 'making tax digital readiness',
                'bookkeeping outsourcing', 'fee pressure from challengers']

    def gather(angle, breadth):
        """What retrieval does: one angle in, many genuinely distinct sources out."""
        return [row('https://publisher-{}.example/article'.format(i),
                    angle=angle,
                    title='A report on {}'.format(subjects[i]))
                for i in range(breadth)]

    thin = gather('the only angle', breadth=2)
    wide = gather('the only angle', breadth=20)

    thin_result = independence.corroboration(thin)
    wide_result = independence.corroboration(wide)

    assert wide_result['groups'] > thin_result['groups'], 'the fan-out really did amplify the group count'
    assert thin_result['corroboration'] == wide_result['corroboration'] == 1, (
        'corroboration must be flat under fan-out; if this fails the gate reads '
        'our own retrieval effort as independent confirmation'
    )
