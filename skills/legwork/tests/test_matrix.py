"""The comparison matrix.

A grid is where a comparison quietly goes wrong: the shape says "complete" while
half the cells are blank and one row carries no evidence at all. These tests pin
the completeness rules that stop a matrix looking more settled than it is.
"""

import matrix


GOOD = """# A comparison

## Comparison matrix

| Vendor | Price | Seat minimum | Native triage |
|---|---|---|---|
| Acme | 30 USD/seat [1] | 5 [1] | No [2] |
| Contoso | 22 USD/seat [3] | 1 [3] | Yes [4] |

## Findings
"""


def parse(text=GOOD):
    return matrix.parse_matrix(text)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_a_report_with_no_matrix_section_parses_as_none():
    assert matrix.parse_matrix('# A report\n\n## Findings\n\nProse.\n') is None


def test_the_first_column_is_the_entity_and_the_rest_are_fields():
    parsed = parse()
    assert parsed['entity_label'] == 'Vendor'
    assert parsed['fields'] == ['Price', 'Seat minimum', 'Native triage']


def test_every_entity_row_is_captured():
    parsed = parse()
    assert [row['entity'] for row in parsed['rows']] == ['Acme', 'Contoso']


def test_cells_are_keyed_by_field():
    parsed = parse()
    assert parsed['rows'][0]['cells']['Price'] == '30 USD/seat [1]'


def test_the_separator_row_is_not_an_entity():
    parsed = parse()
    assert all(row['entity'] != '---' for row in parsed['rows'])


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------

def test_a_complete_cited_matrix_has_no_problems():
    assert matrix.check_matrix(parse())['problems'] == []


def test_a_blank_cell_is_a_problem_because_it_reads_as_settled():
    text = GOOD.replace('| Acme | 30 USD/seat [1] | 5 [1] | No [2] |',
                        '| Acme | 30 USD/seat [1] |  | No [2] |')
    result = matrix.check_matrix(matrix.parse_matrix(text))
    assert any('Acme' in p and 'Seat minimum' in p for p in result['problems'])


def test_an_explicit_unknown_is_accepted_where_a_blank_is_not():
    """Saying "we could not establish this" is a result. Leaving it blank is not."""
    text = GOOD.replace('| Acme | 30 USD/seat [1] | 5 [1] | No [2] |',
                        '| Acme | 30 USD/seat [1] | [unknown] | No [2] |')
    result = matrix.check_matrix(matrix.parse_matrix(text))
    assert result['problems'] == []
    assert result['unknown_cells'] == 1


def test_a_row_with_no_citation_anywhere_is_a_problem():
    text = GOOD.replace('| Contoso | 22 USD/seat [3] | 1 [3] | Yes [4] |',
                        '| Contoso | 22 USD/seat | 1 | Yes |')
    result = matrix.check_matrix(matrix.parse_matrix(text))
    assert any('Contoso' in p and 'citation' in p for p in result['problems'])


def test_a_row_that_is_entirely_unknown_needs_no_citation():
    """Nothing was established, so there is nothing to cite. The row still belongs
    in the table: it records that the entity was looked at and came back empty."""
    text = GOOD.replace('| Contoso | 22 USD/seat [3] | 1 [3] | Yes [4] |',
                        '| Contoso | [unknown] | [unknown] | [unknown] |')
    result = matrix.check_matrix(matrix.parse_matrix(text))
    assert result['problems'] == []


def test_a_ragged_row_is_a_problem():
    text = GOOD.replace('| Contoso | 22 USD/seat [3] | 1 [3] | Yes [4] |',
                        '| Contoso | 22 USD/seat [3] |')
    result = matrix.check_matrix(matrix.parse_matrix(text))
    assert any('columns' in p for p in result['problems'])


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def test_coverage_reports_the_share_of_cells_actually_established():
    text = GOOD.replace('| Contoso | 22 USD/seat [3] | 1 [3] | Yes [4] |',
                        '| Contoso | [unknown] | [unknown] | [unknown] |')
    result = matrix.check_matrix(matrix.parse_matrix(text))
    assert result['cells'] == 6
    assert result['unknown_cells'] == 3
    assert result['coverage'] == 0.5


def test_full_coverage_is_one():
    assert matrix.check_matrix(parse())['coverage'] == 1.0
