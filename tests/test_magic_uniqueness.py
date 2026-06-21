"""Test that all magic numbers defined in `magic_registry` are unique.

The system relies on each method/brain having a distinct identifier. This test
ensures the Enum does not produce duplicate values.
"""

from magic_registry import MagicNumber


def test_magic_numbers_unique():
    values = [member.value for member in MagicNumber]
    assert len(values) == len(set(values)), "Duplicate magic numbers detected"
