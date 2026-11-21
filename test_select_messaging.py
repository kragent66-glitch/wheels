import json
import tempfile
from pathlib import Path
from unittest import mock
import unittest

from scripts import gap_wheels


class TestSelectMessaging(unittest.TestCase):
    """Test that select() produces correct messaging for different test result scenarios."""
    
    def test_select_messaging_distinguishes_failures_from_no_results(self):
        """Test that select() distinguishes between failed tests and no test results."""
        # Test data: a staged wheel
        wheel_name = "zstandard-0.25.0-cp315-cp315-win_amd64.whl"
        staged = [{
            "name": "zstandard",
            "version": "0.25.0", 
            "target": "3.15 win-amd64",
            "wheel": wheel_name,
            "sha256": "a" * 64,
        }]
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            
            # Create the wheel file
            (tmp / wheel_name).write_bytes(b"fake wheel content")
            
            with mock.patch('scripts.gap_wheels.tool_provenance_valid', return_value=True), \
                 mock.patch('scripts.gap_wheels.recipe_records_valid', return_value=True), \
                 mock.patch('scripts.gap_wheels.sha256', lambda p: "a" * 64):
                
                # Case 1: Test passed - should publish
                tested_passed = {"3.15 win-amd64": {wheel_name: True}}
                new, lines = gap_wheels.select(staged, tested_passed, tmp, {})
                self.assertEqual(len(new), 1)  # Should publish
                self.assertEqual(lines[0], f"{wheel_name}: published")
                
                # Case 2: Test failed - should show failed message
                tested_failed = {"3.15 win-amd64": {wheel_name: False}}
                new, lines = gap_wheels.select(staged, tested_failed, tmp, {})
                self.assertEqual(len(new), 0)  # Should not publish
                self.assertEqual(lines[0], f"{wheel_name}: failed the install test on a fresh runner; not published")
                
                # Case 3: No test result for target - should show no result message
                tested_no_result = {}  # No target in tested dict
                new, lines = gap_wheels.select(staged, tested_no_result, tmp, {})
                self.assertEqual(len(new), 0)  # Should not publish
                self.assertEqual(lines[0], f"{wheel_name}: no install-test result for 3.15 win-amd64 (the test job didn't finish or its result couldn't be read); not published")
                
                # Case 4: Test result exists but no answer for this wheel - should show no answer message
                tested_partial = {"3.15 win-amd64": {"other-wheel.whl": True}}  # Has target but not this wheel
                new, lines = gap_wheels.select(staged, tested_partial, tmp, {})
                self.assertEqual(len(new), 0)  # Should not publish
                self.assertEqual(lines[0], f"{wheel_name}: the install test for 3.15 win-amd64 gave no answer for it; not published")


if __name__ == "__main__":
    unittest.main()