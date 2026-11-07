from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rust_docs_pp_cli.models import Example, Page
from rust_docs_pp_cli.store import Store


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "cli.db")
        with Store(self.db) as store:
            store.replace_source(
                "book",
                [
                    Page(
                        url="https://doc.rust-lang.org/book/ownership.html",
                        title="Ownership",
                        source="book",
                        section="root",
                        slug="ownership",
                        content="The borrow checker validates references.",
                        examples=[Example("rust", 'let value = String::from("hello");')],
                    )
                ],
            )
        self.env = os.environ.copy()
        root = Path(__file__).resolve().parents[1]
        self.env["PYTHONPATH"] = str(root / "src")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rust_docs_pp_cli", *args],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

    def test_json_flags_work_after_subcommand(self) -> None:
        result = self.cli("which", "borrow checker", "--db", self.db, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["matches"][0]["slug"], "ownership")

    def test_context_and_compact_examples(self) -> None:
        result = self.cli("context", "ownership", "--json", "--db", self.db)
        self.assertIn("borrow checker", json.loads(result.stdout)["content"])
        result = self.cli("examples", "String", "--compact", "--json", "--db", self.db)
        example = json.loads(result.stdout)["examples"][0]
        self.assertNotIn("rank", example)
        self.assertIn("String::from", example["code"])

    def test_not_found_has_typed_exit_and_json_error(self) -> None:
        result = self.cli("context", "missing", "--db", self.db, "--json")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["exit_code"], 3)

    def test_doctor_and_version(self) -> None:
        doctor = self.cli("doctor", "--json", "--db", self.db)
        self.assertTrue(json.loads(doctor.stdout)["ok"])
        version = self.cli("version", "--json", "--db", self.db)
        self.assertRegex(json.loads(version.stdout)["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
