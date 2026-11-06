"""pr-reviewer.py 시험. 표준 라이브러리만 쓴다.

    python3 -m unittest discover -s pr-reviewer/tests

GitHub · git · claude 는 부르지 않는다. 필요한 함수만 바꿔 끼운다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "pr-reviewer.py"


def load(home: Path):
    """PR_REVIEWER_HOME 을 임시 폴더로 두고 스크립트를 새로 읽는다."""
    os.environ["PR_REVIEWER_HOME"] = str(home)
    spec = importlib.util.spec_from_file_location(f"prr_{id(home)}", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="prr-test-"))
        self.m = load(self.home)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.pop("PR_REVIEWER_HOME", None)

    def config(self, **values) -> dict:
        self.m.write_json(self.m.CONFIG, values)
        return self.m.load_config()


def thread(*authors: str, resolved: bool = False) -> dict:
    nodes = [{"author": {"login": a}} for a in authors]
    return {"isResolved": resolved, "first": {"nodes": nodes[:1]}, "last": {"nodes": nodes[-1:]},
            "all": {"nodes": nodes}}


def gql_pr(**over) -> dict:
    """GraphQL 이 주는 열린 PR 한 건."""
    pr = {
        "number": 1, "title": "feat: x", "url": "https://github.com/o/app/pull/1", "isDraft": False,
        "headRefOid": "a" * 40, "headRefName": "feature/x", "isCrossRepository": False,
        "author": {"login": "alice"}, "reviewDecision": None, "mergeable": "MERGEABLE",
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
        "recent": {"nodes": [{"commit": {"oid": "a" * 40, "parents": {"totalCount": 1}}}]},
        "reviews": {"nodes": []}, "comments": {"nodes": []}, "reviewThreads": {"nodes": []},
    }
    pr.update(over)
    return pr


class BotLogins(Base):
    def test_설정한_봇은_사람_답글로_치지_않는다(self):
        self.config(repos={}, bot_logins=["Our-Review-Bot"])
        pr = gql_pr(reviewThreads={"nodes": [thread("me", "our-review-bot")]})
        self.assertNotEqual(self.m.team_action(pr, "me", {}, False), "Re-review")
        mine = gql_pr(author={"login": "me"}, reviewThreads={"nodes": [thread("our-review-bot")]})
        self.assertNotEqual(self.m.my_action(mine, "me", False), "Reply")
        self.assertTrue(self.m.is_bot("app/our-review-bot"))

    def test_설정에_없으면_사람이다(self):
        self.config(repos={})
        pr = gql_pr(reviewThreads={"nodes": [thread("me", "our-review-bot")]})
        self.assertEqual(self.m.team_action(pr, "me", {}, False), "Re-review")
        self.assertTrue(self.m.is_bot("renovate[bot]"))


if __name__ == "__main__":
    unittest.main()
