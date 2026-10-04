"""เรียกชุดทดสอบตรรกะหน้าเว็บ (Node.js) จาก unittest — ข้ามถ้าไม่มี node"""

import helpers

import os
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "ไม่มี Node.js")
class TestFrontendLogic(unittest.TestCase):
    def test_node_suite(self):
        script = os.path.join(helpers.ROOT, "tests", "frontend_logic.test.mjs")
        proc = subprocess.run(["node", script], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_js_syntax(self):
        proc = subprocess.run(["node", "--check", os.path.join(helpers.ROOT, "static", "js", "app.js")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
