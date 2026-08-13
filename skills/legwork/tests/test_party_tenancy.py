"""Multi-tenant hosts: the platform is not the party.

A registrable domain identifies a party in the ordinary case of one
organisation per domain. It does not on a host that rents space to unrelated
publishers - github.com, arxiv.org, substack.com - where treating the platform
as the voice merges independent parties into one and understates what a run
actually established.

The correction has to hold in both directions, so the last two tests here are
the load-bearing ones: more parties must not buy more corroboration when they
all arrived down one line of enquiry.
"""

import independence


def row(url, angle='an angle', title='', kind='press'):
    return {'url': url, 'angle': angle, 'title': title, 'kind': kind}


# ---------------------------------------------------------------------------
# Path tenancy
# ---------------------------------------------------------------------------

def test_two_orgs_on_one_code_host_are_two_parties():
    assert independence.party_of('https://github.com/acme/tool') != \
        independence.party_of('https://github.com/rival/tool')


def test_one_org_on_one_code_host_is_one_party_across_repos():
    assert independence.party_of('https://github.com/acme/tool') == \
        independence.party_of('https://github.com/acme/other-tool')


def test_raw_content_host_carries_the_org_too():
    assert independence.party_of('https://raw.githubusercontent.com/acme/t/main/README.md') == \
        independence.party_of('https://raw.githubusercontent.com/acme/other/main/x.md')


def test_the_bare_platform_url_falls_back_to_the_platform():
    assert independence.party_of('https://github.com/') == 'github.com'


# ---------------------------------------------------------------------------
# Document tenancy
# ---------------------------------------------------------------------------

def test_one_paper_reached_three_ways_is_one_party():
    parties = {
        independence.party_of('https://arxiv.org/abs/2607.25398'),
        independence.party_of('https://arxiv.org/pdf/2607.25398'),
        independence.party_of('https://arxiv.org/html/2607.25398'),
    }
    assert len(parties) == 1


def test_three_unrelated_papers_are_three_parties():
    parties = {
        independence.party_of('https://arxiv.org/abs/2607.25398'),
        independence.party_of('https://arxiv.org/html/2608.02639'),
        independence.party_of('https://arxiv.org/abs/2601.08536'),
    }
    assert len(parties) == 3


def test_three_unrelated_papers_from_three_angles_corroborate():
    """The case that motivated this: a run reading three independent research
    teams was scored as having read one voice."""
    rows = [
        row('https://arxiv.org/abs/2607.25398', angle='does it hold', title='Handbook'),
        row('https://arxiv.org/html/2608.02639', angle='does it collapse', title='Stacking'),
        row('https://arxiv.org/abs/2601.08536', angle='can it be measured', title='Bench II'),
    ]
    assert independence.corroboration(rows)['corroboration'] == 3


# ---------------------------------------------------------------------------
# Subdomain tenancy
# ---------------------------------------------------------------------------

def test_two_newsletters_on_one_publishing_host_are_two_parties():
    assert independence.party_of('https://acme.substack.com/p/one') != \
        independence.party_of('https://rival.substack.com/p/two')


def test_an_ordinary_subdomain_still_collapses_to_its_registrant():
    assert independence.party_of('https://learn.microsoft.com/x') == \
        independence.party_of('https://microsoft.com/y') == 'microsoft.com'


# ---------------------------------------------------------------------------
# Local evidence
# ---------------------------------------------------------------------------

def test_every_local_file_is_one_voice():
    """Evidence read from disk is one party however many files it spans -
    otherwise a run could corroborate itself out of its own working copy."""
    rows = [
        row('file:///repo/a.md', angle='what does the repo do', title='A'),
        row('file:///repo/b.md', angle='what does the repo say', title='B'),
        row('file:///repo/c.md', angle='what does the repo hold', title='C'),
    ]
    assert independence.corroboration(rows)['corroboration'] == 1


# ---------------------------------------------------------------------------
# The invariant this change could have broken
# ---------------------------------------------------------------------------

def test_many_tenants_from_one_angle_are_still_one_confirmation():
    """Splitting a platform into tenants must not become a way to manufacture
    corroboration by fanning out harder down a single line of enquiry."""
    rows = [row('https://github.com/org{}/repo'.format(n),
                angle='who else ships this',
                title='Project {}'.format(n)) for n in range(6)]
    assert independence.corroboration(rows)['corroboration'] == 1


def test_tenancy_does_not_hide_a_dominant_party():
    """Eight pages from one org are still one party at portfolio level, so a run
    resting on that org is still reported as concentrated."""
    rows = [row('https://github.com/acme/repo{}'.format(n),
                angle='angle {}'.format(n),
                title='Acme {}'.format(n)) for n in range(8)]
    result = independence.portfolio(rows)
    assert result['top_party'] == 'github.com/acme'
    assert result['top_party_share'] == 1.0
    assert not result['passed']
