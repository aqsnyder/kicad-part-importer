"""Checks on the documentation that can be made without a human: commands that
must work as shown, claims that must match the behaviour, and the --help text
that docs/cli.md reproduces."""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import libtest_helpers as H

DOCS = [H.REPO / "README.md", H.REPO / "CONTRIBUTING.md"] + sorted((H.REPO / "docs").glob("*.md"))


class Commands(unittest.TestCase):
    def test_git_init_names_the_branch(self):
        # A bare `git init` makes "master" wherever init.defaultBranch is unset (Git
        # for Windows sets it system-wide), and the `git push -u origin main` after it fails.
        bare = []
        for doc in DOCS:
            for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                for m in re.finditer(r"\bgit init\b([^&;|\n]*)", line):
                    if not re.search(r"(^|\s)(-b|--initial-branch)(\s|=)", m.group(1)):
                        bare.append("%s:%d: %s" % (doc.name, n, line.strip()))
        self.assertEqual(bare, [])


class PromptClaims(unittest.TestCase):
    """A prompt waits while stdin is open (a terminal, a pipe nobody closes); only
    a closed stdin (or Ctrl+C) stops it with exit code 2. The docs must say so,
    not promise that a prompt never hangs."""

    def test_docs_do_not_promise_a_prompt_never_waits(self):
        for doc in DOCS:
            text = " ".join(doc.read_text(encoding="utf-8").split())
            self.assertNotRegex(text, r"(?i)never (hangs|waits|blocks)", doc.name)

    def test_a_prompt_waits_while_stdin_is_open(self):
        with tempfile.TemporaryDirectory() as t:
            lib = H.make_library(Path(t) / "lib")
            z = Path(t) / "p.zip"
            H.ti_zip(z)
            p = subprocess.Popen([sys.executable, "-B", "-I", str(H.IMPORTER), "--library", str(lib), str(z)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=H.clean_env())
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    p.wait(timeout=2)  # still at the category menu
            finally:
                out, err = p.communicate(input=b"", timeout=120)  # closing stdin stops it
            self.assertEqual(p.returncode, 2, (out, err))
            self.assertIn(b"stdin closed", err)


@unittest.skipIf(sys.version_info >= (3, 13), "argparse 3.13+ formats options with several flags differently")
class HelpText(unittest.TestCase):
    def test_cli_md_shows_the_current_help(self):
        text = (H.REPO / "docs" / "cli.md").read_text(encoding="utf-8")
        m = re.search(r"```text\n\$ kicad-part-importer --help\n(.*?)```", text, re.S)
        self.assertIsNotNone(m, "no --help block in docs/cli.md")
        r = subprocess.run([sys.executable, "-B", "-I", str(H.IMPORTER), "--help"], capture_output=True,
                           text=True, encoding="utf-8", env=H.clean_env({"COLUMNS": "100"}))
        self.assertEqual(r.returncode, 0, r.stderr)
        actual = r.stdout.replace("\noptional arguments:\n", "\noptions:\n")  # Python 3.9 wording
        self.assertEqual(m.group(1).rstrip("\n").splitlines(), actual.rstrip("\n").splitlines())


if __name__ == "__main__":
    unittest.main()
