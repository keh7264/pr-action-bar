"""pr-reviewer.py 시험. 표준 라이브러리만 쓴다.

    python3 -m unittest discover -s pr-reviewer/tests

GitHub · git · claude 는 부르지 않는다. 필요한 함수만 바꿔 끼운다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
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


class PollMinutes(Base):
    def test_launchd_간격은_poll_minutes_를_따른다(self):
        cfg = self.config(repos={}, poll_minutes=10)
        self.assertIn("<key>StartInterval</key><integer>600</integer>", self.m.plist_text(cfg, "/usr/bin/python3"))

    def test_기본은_5분이고_이상한_값은_기본값(self):
        self.assertIn("<integer>300</integer>", self.m.plist_text(self.config(repos={}), "py"))
        self.assertEqual(self.config(repos={}, poll_minutes="x")["poll_minutes"], 5)
        self.assertEqual(self.config(repos={}, poll_minutes=0)["poll_minutes"], 1)


def gc(login: str, at: str) -> dict:
    """GraphQL 대화 탭 댓글."""
    return {"author": {"login": login}, "createdAt": at}


def gr(login: str, state: str, at: str) -> dict:
    return {"author": {"login": login}, "state": state, "submittedAt": at, "commit": {"oid": "a" * 40}}


class ConversationStatus(Base):
    def setUp(self):
        super().setUp()
        self.config(repos={})

    def test_내_댓글_뒤에_작성자가_대화_탭에_답하면_Re_review(self):
        pr = gql_pr(comments={"nodes": [gc("me", "2026-01-01T00:00:00Z"), gc("alice", "2026-01-02T00:00:00Z")]})
        self.assertEqual(self.m.team_action(pr, "me", {}, False), "Re-review")

    def test_내가_승인한_뒤의_댓글은_세지_않는다(self):
        pr = gql_pr(reviews={"nodes": [gr("me", "APPROVED", "2026-01-01T00:00:00Z")]},
                    comments={"nodes": [gc("alice", "2026-01-02T00:00:00Z")]})
        self.assertEqual(self.m.team_action(pr, "me", {}, False), "Approved")

    def test_내가_아무것도_안_남긴_PR_의_대화는_세지_않는다(self):
        pr = gql_pr(comments={"nodes": [gc("alice", "2026-01-02T00:00:00Z")]})
        self.assertEqual(self.m.team_action(pr, "me", {}, False), "Needs review")

    def test_봇_댓글은_세지_않는다(self):
        pr = gql_pr(comments={"nodes": [gc("me", "2026-01-01T00:00:00Z"), gc("sonar[bot]", "2026-01-02T00:00:00Z")]})
        self.assertNotEqual(self.m.team_action(pr, "me", {}, False), "Re-review")

    def test_내_PR_대화_탭에_질문이_오면_Reply(self):
        pr = gql_pr(author={"login": "me"}, comments={"nodes": [gc("bob", "2026-01-02T00:00:00Z")]})
        self.assertEqual(self.m.my_action(pr, "me", False), "Reply")

    def test_내_PR_에서_승인한_사람의_승인_뒤_댓글은_Reply_가_아니다(self):
        pr = gql_pr(author={"login": "me"}, reviewDecision="APPROVED",
                    reviews={"nodes": [gr("bob", "APPROVED", "2026-01-02T00:00:00Z")]},
                    comments={"nodes": [gc("bob", "2026-01-02T00:00:01Z")]})
        self.assertEqual(self.m.my_action(pr, "me", False), "Merge")

    def test_내가_답한_뒤에는_Reply_가_아니다(self):
        pr = gql_pr(author={"login": "me"}, comments={"nodes": [gc("bob", "2026-01-02T00:00:00Z"),
                                                                 gc("me", "2026-01-03T00:00:00Z")]})
        self.assertNotEqual(self.m.my_action(pr, "me", False), "Reply")


def rc(id_: int, login: str, at: str, body: str = "...", **over) -> dict:
    """REST 댓글 (리뷰 스레드 · 대화 탭 공통)."""
    return {"id": id_, "user": {"login": login}, "created_at": at, "body": body, **over}


class ConversationReplies(Base):
    """check_replies: 대화 탭 댓글도 답글 리뷰로 넘긴다."""

    def setUp(self):
        super().setUp()
        self.cfg = self.config(repos={"app": str(self.home)})
        self.state = {}
        self.ps = self.m.pr_state(self.state, "app", 1)
        self.ps.update(session_id="sid", reply_cursor=0, issue_cursor=0)
        self.m.worktree_path("app", 1).mkdir(parents=True)
        self.threads, self.issue, self.reviews, self.calls = [], [], [], []
        m = self.m
        m.review_comments = lambda *a: self.threads
        m.issue_comments = lambda *a: self.issue
        m.pr_reviews = lambda *a: self.reviews
        m.terminal_send = lambda *a: False
        m.notify = lambda *a, **k: None
        m.claude = lambda cfg, wt, text, **k: self.calls.append(text) or {"result": "답글 리뷰"}
        self.git_calls, self.git_out = [], ""
        m.prepare_worktree = lambda cfg, repo, repo_dir, pr, ps: m.worktree_path(repo, pr["number"])
        m.git = lambda cfg, *args, cwd, **k: (self.git_calls.append(args)
                                              or subprocess.CompletedProcess(args, 0, self.git_out, ""))
        self.pr = {"number": 1, "url": "u", "headRefOid": "a" * 40, "baseRefName": "main"}

    def run_check(self):
        self.m.check_replies(self.cfg, self.state, "me", "app", "/repo", self.pr)

    def test_작성자가_대화_탭에_답하면_답글_리뷰를_돌린다(self):
        self.issue = [rc(10, "me", "2026-01-01T00:00:00Z", "이 부분 확인 부탁"),
                      rc(11, "alice", "2026-01-02T00:00:00Z", "고쳤습니다")]
        self.run_check()
        self.assertEqual(len(self.calls), 1)
        thread_file = re_find_path(self.calls[0])
        text = Path(thread_file).read_text()
        self.assertIn("## 대화 탭", text)
        self.assertIn("고쳤습니다", text)
        self.assertEqual(self.ps["issue_cursor"], 11)

    def test_승인_뒤_댓글과_봇_댓글은_넘기지_않는다(self):
        self.reviews = [{"id": 1, "user": {"login": "me"}, "state": "APPROVED", "submitted_at": "2026-01-01T00:00:00Z"}]
        self.issue = [rc(11, "alice", "2026-01-02T00:00:00Z", "감사합니다"),
                      rc(12, "ci[bot]", "2026-01-02T00:00:00Z")]
        self.run_check()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ps["issue_cursor"], 12)

    def test_예전_상태에는_대화_기준점을_지금으로_잡는다(self):
        del self.ps["issue_cursor"]
        self.issue = [rc(10, "me", "2026-01-01T00:00:00Z"), rc(11, "alice", "2026-01-02T00:00:00Z")]
        self.run_check()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ps["issue_cursor"], 11)

    def test_리뷰_스레드_답글도_그대로_본다(self):
        self.threads = [rc(5, "me", "2026-01-01T00:00:00Z", "여기 null?", path="a.py", line=3),
                        rc(6, "alice", "2026-01-02T00:00:00Z", "막혀 있어요", in_reply_to_id=5)]
        self.run_check()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.ps["reply_cursor"], 6)

    def test_답글_리뷰에_이전_리뷰_이후_커밋을_넣는다(self):
        self.ps["reviewed_sha"] = "b" * 40
        self.git_out = "- 1234567 fix: null 처리\n"
        self.issue = [rc(10, "me", "2026-01-01T00:00:00Z"), rc(11, "alice", "2026-01-02T00:00:00Z")]
        self.run_check()
        self.assertIn("이후 커밋 (base 머지 제외)", self.calls[0])
        self.assertIn("1234567 fix: null 처리", self.calls[0])
        self.assertIn("--no-merges", self.git_calls[0])
        self.assertIn(f"{'b' * 40}..refs/pr-reviewer/1", self.git_calls[0])
        self.assertEqual(self.ps["seen_sha"], "a" * 40)

    def test_두_번째_답글부터는_지난_답글_리뷰_뒤의_커밋만(self):
        self.ps.update(reviewed_sha="b" * 40, seen_sha="c" * 40)
        self.issue = [rc(10, "me", "2026-01-01T00:00:00Z"), rc(11, "alice", "2026-01-02T00:00:00Z")]
        self.run_check()
        self.assertIn(f"{'c' * 40}..refs/pr-reviewer/1", self.git_calls[0])
        self.assertIn("코드 커밋 없음", self.calls[0])

    def test_worktree_를_못_옮기면_그렇다고_적는다(self):
        self.ps["reviewed_sha"] = "a" * 40
        self.m.prepare_worktree = lambda *a: None
        self.issue = [rc(10, "me", "2026-01-01T00:00:00Z"), rc(11, "alice", "2026-01-02T00:00:00Z")]
        self.run_check()
        self.assertIn("새 커밋 없음", self.calls[0])
        self.assertIn("옮기지 못했다", self.calls[0])


REVIEW_JSON = {
    "pr_summary": "결제 완료 문구를 바꾼다. null 처리가 빠졌다.",
    "findings": [
        {"title": "문구 오타", "location": "a.ts:3", "category": "넘겨도 됨", "problem": "오타",
         "scenario": "항상", "fix": "고친다", "reason": "표시만"},
        {"title": "null 이면 터진다", "location": "b.ts:10", "category": "꼭 수정", "problem": "user 가 null",
         "scenario": "비회원 결제", "fix": "가드 추가\n```diff\n- a.b\n+ a?.b\n```", "reason": "호출부에서 null 가능"},
    ],
}


class ReviewFormat(Base):
    pr = {"number": 1, "title": "feat: x", "url": "u", "headRefOid": "a" * 40}

    def render(self, raw: str):
        return self.m.render_review("app", self.pr, raw, "sid", Path("/wt"), 65)

    def test_JSON_을_마크다운으로_그리고_분류를_센다(self):
        text, data = self.render(json.dumps(REVIEW_JSON, ensure_ascii=False))
        self.assertIsNotNone(data)
        self.assertIn("꼭 1 · 넘겨도 1", text)
        self.assertLess(text.index("null 이면 터진다"), text.index("문구 오타"))  # 꼭 수정이 먼저
        self.assertIn("`b.ts:10` · 꼭 수정", text)
        self.assertIn("```diff\n- a.b\n+ a?.b\n```", text)

    def test_코드블록이나_앞뒤_말이_붙어도_읽는다(self):
        body = json.dumps(REVIEW_JSON, ensure_ascii=False)
        for raw in (f"```json\n{body}\n```", f"정리했습니다.\n{body}\n끝"):
            self.assertIsNotNone(self.m.parse_review(raw), raw[:20])

    def test_지적이_없으면_지적_없음(self):
        text, data = self.render('{"pr_summary": "괜찮다", "findings": []}')
        self.assertIn("· 지적 없음", text)

    def test_형식이_깨지면_원문을_보존하고_형식_확인_필요(self):
        raw = "## PR 요약\n\n마크다운으로 답해 버렸다"
        text, data = self.render(raw)
        self.assertIsNone(data)
        self.assertIn("형식 확인 필요", text)
        self.assertIn("마크다운으로 답해 버렸다", text)

    def test_모르는_분류는_따로_센다(self):
        bad = {"pr_summary": "s", "findings": [{"title": "t", "category": "중요"}]}
        self.assertEqual(self.m.tally_of(bad), "분류 확인 필요 1")


class ReviewFlow(Base):
    """review_pr 한 바퀴: 리뷰 → 재검토 → 정리, 리뷰 파일 · JSON · 알림."""

    def setUp(self):
        super().setUp()
        self.cfg = self.config(repos={"app": "/repo"})
        self.state, self.prompts, self.notes = {}, [], []
        m = self.m
        self.pr = {"number": 1, "title": "feat: x", "url": "u", "headRefOid": "a" * 40, "baseRefName": "main",
                   "state": "OPEN", "isDraft": False, "author": {"login": "alice"}}
        m.view_pr = lambda *a: dict(self.pr)
        m.cursors_now = lambda *a: {"reply_cursor": 5, "issue_cursor": 7}
        m.prepare_worktree = lambda cfg, repo, repo_dir, pr, ps: self.home / "wt-app-1"
        m.write_status_safely = lambda *a: None
        m.terminal_prepare = lambda *a, **k: None
        m.notify = lambda cfg, state, title, msg, **k: self.notes.append(title)
        self.final = json.dumps(REVIEW_JSON, ensure_ascii=False)

        def fake_claude(cfg, wt, text, **k):
            self.prompts.append(text)
            return {"session_id": "sid", "result": self.final if len(self.prompts) == 3 else "..."}
        m.claude = fake_claude

    def test_리뷰_파일과_JSON_을_쓰고_알린다(self):
        self.m.review_pr(self.cfg, self.state, "app", "/repo", self.pr)
        ps = self.state["repos"]["app"]["prs"]["1"]
        self.assertEqual(len(self.prompts), 3)
        self.assertTrue(self.prompts[0].startswith("/code-review 1 high"))
        self.assertIn("JSON", self.prompts[2])
        self.assertTrue(Path(ps["review_file"]).exists())
        self.assertTrue(Path(ps["review_file"]).with_suffix(".json").exists())
        self.assertEqual((ps["reply_cursor"], ps["issue_cursor"], ps["format_ok"]), (5, 7, True))
        self.assertEqual(self.notes, ["app#1 리뷰 완료"])

    def test_형식이_깨지면_알림에_적는다(self):
        self.final = "그냥 글"
        self.m.review_pr(self.cfg, self.state, "app", "/repo", self.pr)
        self.assertEqual(self.notes, ["app#1 리뷰 완료 (형식 확인 필요)"])
        self.assertFalse(self.state["repos"]["app"]["prs"]["1"]["format_ok"])


def re_find_path(text: str) -> str:
    import re
    return re.search(r"(/\S+\.md)", text).group(1)


if __name__ == "__main__":
    unittest.main()
