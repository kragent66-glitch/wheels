import json
import tempfile
from pathlib import Path
from unittest import mock
import unittest

from scripts import gap_wheels


class TestReadTested(unittest.TestCase):
    """Test that read_tested() properly handles True and False values."""
    
    def test_read_tested_keeps_true_and_false_drops_non_bool(self):
        """Test that read_tested() keeps both True and False values, drops non-bool values."""
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            
            # Create test artifacts for different scenarios
            target_dir = tmp / "tested-3.15-win-amd64"
            target_dir.mkdir()
            
            # Test data with mixed boolean and non-boolean values
            test_data = {
                "tested": {
                    "wheel1-1.0-py3-none-any.whl": True,
                    "wheel2-1.0-py3-none-any.whl": False,
                    "wheel3-1.0-py3-none-any.whl": "yes",  # non-bool, should be dropped
                    "wheel4-1.0-py3-none-any.whl": 1,      # non-bool, should be dropped
                    "wheel5-1.0-py3-none-any.whl": None,   # non-bool, should be dropped
                }
            }
            
            (target_dir / "tested.json").write_text(json.dumps(test_data))
            
            # Mock the build_lab.TARGETS to include our test target
            with mock.patch('scripts.gap_wheels.build_lab.TARGETS', ['3.15 win-amd64']):
                result = gap_wheels.read_tested(tmp)
                
                # Should have True and False values, but not the non-bool ones
                self.assertEqual(result, {
                    "3.15 win-amd64": {
                        "wheel1-1.0-py3-none-any.whl": True,
                        "wheel2-1.0-py3-none-any.whl": False,
                    }
                })
                
                # Verify non-bool values were dropped
                self.assertNotIn("wheel3-1.0-py3-none-any.whl", result["3.15 win-amd64"])
                self.assertNotIn("wheel4-1.0-py3-none-any.whl", result["3.15 win-amd64"])
                self.assertNotIn("wheel5-1.0-py3-none-any.whl", result["3.15 win-amd64"])


if __name__ == "__main__":
    unittest.main()