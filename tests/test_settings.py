"""Local key loading must work without leaking into committed configuration."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from superchat.settings import load_local_env


class SettingsTests(unittest.TestCase):
    def test_env_file_loads_key_and_preserves_process_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# local key\nOPENROUTER_API_KEY='file-key'\n"
                            "OPENROUTER_MODEL=openai/gpt-5-mini\n"
                            "UNRELATED=value\n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENROUTER_MODEL": "chosen-model"}, clear=True):
                load_local_env(path)
                self.assertEqual(os.environ["OPENROUTER_API_KEY"], "file-key")
                self.assertEqual(os.environ["OPENROUTER_MODEL"], "chosen-model")
                self.assertNotIn("UNRELATED", os.environ)


if __name__ == "__main__":
    unittest.main()
