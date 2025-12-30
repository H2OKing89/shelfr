"""Test BBCode signature output matches known working format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Non-breaking space character
NBSP = "\u00a0"

# Load the expected signature from the sample file
_SAMPLES_DIR = Path(__file__).parent.parent / "samples"
_EXPECTED_SIG_FILE = _SAMPLES_DIR / "bbcode_sig_expected.json"

def _load_expected_signature() -> str:
    """Load expected signature from sample file."""
    with _EXPECTED_SIG_FILE.open() as f:
        return json.load(f)["signature"]


class TestBBCodeSignature:
    """Test signature BBCode generation."""

    def test_convert_newlines_function(self) -> None:
        """Test the _convert_newlines_for_mam function directly."""
        from shelfr.metadata import _convert_newlines_for_mam

        # Multiline input (like the template file)
        multiline_input = """[center][pre][color=#06B6D4]╭───────────────────────────────────────────────────────────╮
│                                                           │
│[/color]  [b][color=#FF10F0]██╗  ██╗██████╗  ██████╗ ██╗  ██╗██╗███╗   ██╗ ██████╗[/color][/b]   [color=#06B6D4]│
│[/color]  [b][color=#EC4899]██║  ██║╚════██╗██╔═══██╗██║ ██╔╝██║████╗  ██║██╔════╝[/color][/b]   [color=#06B6D4]│
│[/color]  [b][color=#C19EE0]███████║ █████╔╝██║   ██║█████╔╝ ██║██╔██╗ ██║██║  ███╗[/color][/b]  [color=#06B6D4]│
│[/color]  [b][color=#9D4EDD]██╔══██║██╔═══╝ ██║   ██║██╔═██╗ ██║██║╚██╗██║██║   ██║[/color][/b]  [color=#06B6D4]│
│[/color]  [b][color=#7C3AED]██║  ██║███████╗╚██████╔╝██║  ██╗██║██║ ╚████║╚██████╔╝[/color][/b]  [color=#06B6D4]│
│[/color]  [b][color=#6D28D9]╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝ ╚═════╝[/color][/b]   [color=#06B6D4]│
│                                                           │
│[/color]              [b][color=#06B6D4]Hydrate, Validate, and Organize[/color][/b][color=#06B6D4]              │
│                                                           │
╰───────────────────────────────────────────────────────────╯[/color][/pre][color=#06B6D4][i]Proudly Presents[/i][/color][/center]"""

        result = _convert_newlines_for_mam(multiline_input)
        expected = _load_expected_signature()
        
        # Debug: show differences
        if result != expected:
            print("\n=== EXPECTED ===")
            print(repr(expected[:500]))
            print("\n=== GOT ===")
            print(repr(result[:500]))
            
            # Find first difference
            for i, (a, b) in enumerate(zip(expected, result)):
                if a != b:
                    print(f"\nFirst diff at position {i}:")
                    print(f"  Expected: {repr(expected[max(0,i-20):i+20])}")
                    print(f"  Got:      {repr(result[max(0,i-20):i+20])}")
                    break
            
            if len(expected) != len(result):
                print(f"\nLength diff: expected {len(expected)}, got {len(result)}")

        assert result == expected

    def test_simple_pre_block(self) -> None:
        """Test simple [pre] block - newlines to [br], spaces to nbsp."""
        from shelfr.metadata import _convert_newlines_for_mam

        input_text = "[pre]line 1\nline 2\nline 3[/pre]"
        expected = f"[pre]line{NBSP}1[br]line{NBSP}2[br]line{NBSP}3[/pre]"
        
        result = _convert_newlines_for_mam(input_text)
        assert result == expected

    def test_mixed_pre_and_regular(self) -> None:
        """Test mixed content - newlines removed outside [pre], converted inside."""
        from shelfr.metadata import _convert_newlines_for_mam

        input_text = "before text\n[pre]in pre\nblock[/pre]\nafter text"
        expected = f"before text[pre]in{NBSP}pre[br]block[/pre]after text"
        
        result = _convert_newlines_for_mam(input_text)
        assert result == expected

    def test_pre_block_spaces_converted_to_nbsp(self) -> None:
        """Verify that spaces inside [pre] blocks are converted to non-breaking spaces."""
        from shelfr.metadata import _convert_newlines_for_mam

        # Simple case with multiple spaces
        input_text = "[pre]hello    world[/pre]"
        result = _convert_newlines_for_mam(input_text)
        
        # Should have nbsp, not regular spaces
        assert " " not in result.replace("[pre]", "").replace("[/pre]", "")
        assert NBSP in result
        assert f"hello{NBSP}{NBSP}{NBSP}{NBSP}world" in result

    def test_spaces_outside_pre_preserved(self) -> None:
        """Verify that spaces outside [pre] blocks are NOT converted."""
        from shelfr.metadata import _convert_newlines_for_mam

        input_text = "hello world[pre]in pre[/pre]after text"
        result = _convert_newlines_for_mam(input_text)
        
        # Regular spaces should remain outside [pre]
        assert "hello world" in result
        assert "after text" in result
        # But inside [pre] should be nbsp
        assert f"in{NBSP}pre" in result


def validate_json_signature(json_path: str) -> bool:
    """Validate that a generated JSON file has the correct signature format.
    
    This is a utility function that can be called to verify MAM JSON files.
    
    Args:
        json_path: Path to the JSON file to validate
        
    Returns:
        True if signature is valid, raises AssertionError otherwise
    """
    import re
    
    with open(json_path) as f:
        data = json.load(f)
    
    desc = data.get("description", "")
    
    # Extract signature (up to first [/center][center])
    sig_end = desc.find("[/center][center]")
    signature = desc[:sig_end + len("[/center]")] if sig_end > 0 else ""
    
    expected = _load_expected_signature()
    
    if signature != expected:
        # Find first difference for debugging
        for i, (e, s) in enumerate(zip(expected, signature)):
            if e != s:
                raise AssertionError(
                    f"Signature mismatch at position {i}:\n"
                    f"  Expected: {repr(expected[max(0,i-20):i+20])}\n"
                    f"  Got:      {repr(signature[max(0,i-20):i+20])}"
                )
        if len(expected) != len(signature):
            raise AssertionError(
                f"Signature length mismatch: expected {len(expected)}, got {len(signature)}"
            )
    
    return True


if __name__ == "__main__":
    # Quick manual test
    test = TestBBCodeSignature()
    print("Running test_simple_pre_block...")
    test.test_simple_pre_block()
    print("PASSED\n")
    
    print("Running test_mixed_pre_and_regular...")
    test.test_mixed_pre_and_regular()
    print("PASSED\n")
    
    print("Running test_convert_newlines_function...")
    test.test_convert_newlines_function()
    print("PASSED\n")
    
    print("Running test_pre_block_spaces_converted_to_nbsp...")
    test.test_pre_block_spaces_converted_to_nbsp()
    print("PASSED\n")
    
    print("Running test_spaces_outside_pre_preserved...")
    test.test_spaces_outside_pre_preserved()
    print("PASSED\n")
    
    print("All tests passed!")
