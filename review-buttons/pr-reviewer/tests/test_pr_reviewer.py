"""pr-reviewer.py 시험. 표준 라이브러리만 쓴다.

    python3 -m unittest discover -s review-buttons/pr-reviewer/tests

GitHub · git · claude 는 부르지 않는다. 필요한 함수만 바꿔 끼운다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import contextlib
import io
import sys
import tempfile
import threading
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
        self.m.PLIST = self.home / "launchd.plist"  # 이 맥에 설치된 진짜 launchd 작업을 건드리지 않게

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.pop("PR_REVIEWER_HOME", None)

    def config(self, **values) -> dict:
        values.setdefault("terminal", "none")  # 이 맥에 깔린 Orca · Ghostty 를 따라가지 않게
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
        self.assertTrue(self.m.is_bot("Copilot"))


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


class ReplyBase(Base):
    """답글 · 피드백 확인 준비: GitHub · git · claude 를 바꿔 끼운다."""

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


class ConversationReplies(ReplyBase):
    """check_replies: 대화 탭 댓글도 답글 리뷰로 넘긴다."""

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
        return self.m.render_review(self.config(repos={}), "app", self.pr, raw, "sid", Path("/wt"), 65)

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


class ReviewBase(Base):
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


class ReviewFlow(ReviewBase):
    """review_pr 한 바퀴: 리뷰 → 재검토 → 정리, 리뷰 파일 · JSON · 알림."""

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


class SystemPrompt(Base):
    def setUp(self):
        super().setUp()
        self.app, self.api, self.docs = (self.home / n for n in ("app", "api", "docs"))
        for d in (self.app, self.api, self.docs):
            d.mkdir()
        self.cfg = self.config(repos={"app": str(self.app), "api": str(self.api)}, extra_dirs=[str(self.docs)],
                               review_instructions="금액은 BigDecimal 로만 다룬다")

    def arg(self, args: list[str], flag: str) -> str:
        return args[args.index(flag) + 1]

    def test_로컬_클론_위치와_팀_기준을_시스템_프롬프트에_넣는다(self):
        args = self.m.claude_args(self.cfg, "app")
        text = self.arg(args, "--append-system-prompt")
        self.assertIn(f"- app (이 PR 의 레포): {self.app}", text)
        self.assertIn(f"- api: {self.api}", text)
        self.assertIn(f"- 참고 폴더: {self.docs}", text)
        self.assertIn("금액은 BigDecimal 로만 다룬다", text)

    def test_다른_레포와_참고_폴더를_add_dir_로_연다(self):
        args = self.m.claude_args(self.cfg, "app")
        i = args.index("--add-dir")
        self.assertEqual(args[i + 1:i + 4], [str(self.app), str(self.api), str(self.docs)])
        self.assertEqual(args[i + 4], "--output-format")

    def test_없는_폴더는_빼고_리뷰_탭_명령에도_연다(self):
        cfg = self.config(repos={"app": str(self.app)}, extra_dirs=["/nope"])
        self.assertEqual(self.m.read_dirs(cfg), [str(self.app)])
        self.assertTrue(self.m.resume_command(cfg, "sid").endswith(f"--resume sid --add-dir {self.app}"))

    def test_system_md_가_있으면_그_파일을_쓴다(self):
        self.m.PROMPTS.mkdir(parents=True)
        (self.m.PROMPTS / "system.md").write_text("우리 팀 리뷰어\n{{REPOS}}")
        text = self.m.system_prompt(self.cfg, "app")
        self.assertTrue(text.startswith("우리 팀 리뷰어"))
        self.assertIn("로컬 클론:", text)


class BotFeedback(ReplyBase):
    """봇 PR: 다른 사람이 남긴 줄 코멘트 · 리뷰 본문 · 대화 탭 글을 고칠 목록으로."""

    def setUp(self):
        super().setUp()
        self.cfg = self.config(repos={"app": str(self.home)}, bot_pr_markers=["[bot-fix]"])
        self.ps.update(review_cursor=0)

    def run_feedback(self):
        self.m.check_feedback(self.cfg, self.state, "me", "app", "/repo", self.pr)

    def test_다른_사람의_피드백을_모아_고칠_목록을_만든다(self):
        self.threads = [rc(5, "alice", "2026-01-01T00:00:00Z", "여기 null", path="a.py", line=3)]
        self.reviews = [{"id": 8, "user": {"login": "bob"}, "state": "CHANGES_REQUESTED", "body": "테스트 추가",
                         "submitted_at": "2026-01-01T00:00:00Z"},
                        {"id": 9, "user": {"login": "carol"}, "state": "APPROVED", "body": "",
                         "submitted_at": "2026-01-01T00:00:00Z"}]
        self.issue = [rc(11, "dave", "2026-01-02T00:00:00Z", "문서도?"), rc(12, "me", "2026-01-02T00:00:00Z")]
        self.run_feedback()
        self.assertEqual(len(self.calls), 1)
        self.assertIn("고칠 것과 안 고칠 것", self.calls[0])
        text = Path(re_find_path(self.calls[0])).read_text()
        for word in ("## 리뷰 본문", "테스트 추가", "## 줄 코멘트", "a.py:3", "여기 null", "## 대화 탭", "문서도?"):
            self.assertIn(word, text)
        self.assertNotIn("carol", text)  # 본문 없는 승인은 피드백이 아니다
        self.assertEqual((self.ps["reply_cursor"], self.ps["review_cursor"], self.ps["issue_cursor"]), (5, 9, 12))

    def test_내_글과_봇_글만_있으면_넘기지_않는다(self):
        self.threads = [rc(5, "me", "2026-01-01T00:00:00Z"), rc(6, "lint[bot]", "2026-01-01T00:00:00Z")]
        self.run_feedback()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ps["reply_cursor"], 6)


class BotFirstReview(ReviewBase):
    def test_첫_리뷰에_먼저_달린_리뷰를_넣는다(self):
        self.cfg = self.config(repos={"app": "/repo"}, bot_pr_markers=["[bot-fix]"])
        self.pr["title"] = "[bot-fix] 로그 정리"
        self.state["me"] = "me"
        m = self.m
        m.review_comments = lambda *a: [rc(5, "alice", "2026-01-01T00:00:00Z", "여기 null", path="a.py", line=3)]
        m.pr_reviews = lambda *a: []
        m.issue_comments = lambda *a: []
        self.m.review_pr(self.cfg, self.state, "app", "/repo", self.pr)
        self.assertIn("먼저 남긴 리뷰가", self.prompts[1])
        self.assertIn("여기 null", Path(re_find_path(self.prompts[1])).read_text())
        self.assertEqual(self.state["repos"]["app"]["prs"]["1"]["reply_cursor"], 5)

    def test_먼저_달린_리뷰가_없으면_그_문장은_없다(self):
        self.cfg = self.config(repos={"app": "/repo"}, bot_pr_markers=["[bot-fix]"])
        self.pr["title"] = "[bot-fix] 로그 정리"
        self.m.review_comments = self.m.pr_reviews = self.m.issue_comments = lambda *a: []
        self.m.review_pr(self.cfg, self.state, "app", "/repo", self.pr)
        self.assertNotIn("먼저 남긴 리뷰가", self.prompts[1])
        self.assertIn("고칠 것과 안 고칠 것", self.prompts[1])


class ParallelReviews(Base):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(repos={"app": str(self.home)}, max_parallel_reviews=2)
        self.state = {"repos": {"app": {"seen_initial": "x"}}}
        self.prs = [{"number": n, "title": f"pr {n}", "author": {"login": "alice"}, "isDraft": False,
                     "headRefOid": "a" * 40, "url": "u"} for n in (1, 2, 3)]
        self.active, self.peak, self.replies = 0, 0, []
        self.lock = threading.Lock()
        m = self.m
        m.WAKE_SECONDS = 0.02
        m.my_login = lambda cfg, state: "me"
        m.list_open_prs = lambda *a: self.prs
        m.cleanup_closed = lambda *a: None
        m.write_status_safely = lambda *a, **k: None
        m.check_replies = lambda cfg, state, me, repo, repo_dir, pr: self.replies.append(pr["number"])
        self.hold = lambda pr: None
        m.review_pr = self.fake_review

    def fake_review(self, cfg, state, repo, repo_dir, pr):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            self.hold(pr)
        finally:
            with self.lock:
                self.active -= 1
        self.m.pr_state(state, repo, pr["number"])["reviewed_at"] = "done"

    def test_빈자리만큼_동시에_리뷰한다(self):
        barrier = threading.Barrier(2, timeout=3)
        self.prs = self.prs[:2]
        self.hold = lambda pr: barrier.wait()  # 둘이 동시에 돌지 않으면 시간 초과로 깨진다
        self.m.poll_locked(self.cfg, self.state)
        self.assertEqual(self.peak, 2)
        self.assertFalse(barrier.broken)

    def test_max_parallel_reviews_를_넘지_않고_남은_PR_도_리뷰한다(self):
        self.cfg["max_parallel_reviews"] = 1
        self.hold = lambda pr: threading.Event().wait(0.05)
        self.m.poll_locked(self.cfg, self.state)
        self.assertEqual(self.peak, 1)
        done = [n for n in (1, 2, 3) if self.state["repos"]["app"]["prs"][str(n)].get("reviewed_at")]
        self.assertEqual(done, [1, 2, 3])

    def test_리뷰가_도는_동안에도_다른_PR_답글을_확인한다(self):
        self.cfg["poll_minutes"] = 0.001  # 바퀴를 빨리 돌린다
        self.state["repos"]["app"]["prs"] = {"2": {"session_id": "s", "reviewed_at": "x"}}
        self.prs = self.prs[:2]
        seen_twice = threading.Event()
        self.m.check_replies = lambda cfg, state, me, repo, repo_dir, pr: (
            self.replies.append(pr["number"]), len(self.replies) >= 2 and seen_twice.set())
        self.hold = lambda pr: self.assertTrue(seen_twice.wait(3), "리뷰 중에 답글 확인이 다시 돌지 않았다")
        self.m.poll_locked(self.cfg, self.state)
        self.assertGreaterEqual(len(self.replies), 2)

    def test_리뷰_스레드의_일시_실패는_쉬기로_이어진다(self):
        self.prs = self.prs[:1]
        self.m.notify = lambda *a, **k: None

        def boom(pr):
            raise self.m.Transient("network", "vpn")
        self.hold = boom
        self.m.poll_locked(self.cfg, self.state)
        self.assertTrue(self.m.paused(self.state))
        self.assertEqual(self.state["repos"]["app"]["prs"]["1"]["transient_count"], 1)

    def test_보류된_PR_은_바로_다시_넣지_않는다(self):
        self.prs = self.prs[:1]
        calls = []
        self.m.review_pr = lambda cfg, state, repo, repo_dir, pr: calls.append(pr["number"])  # 보류처럼 그냥 끝난다
        done = threading.Event()
        threading.Thread(target=lambda: (self.m.poll_locked(self.cfg, self.state), done.set()), daemon=True).start()
        self.assertTrue(done.wait(3), "보류된 PR 을 다시 넣으며 루프가 끝나지 않았다")
        self.assertEqual(calls, [1])

    def test_같은_레포는_같은_잠금(self):
        self.assertIs(self.m.repo_lock("/a"), self.m.repo_lock("/a"))
        self.assertIsNot(self.m.repo_lock("/a"), self.m.repo_lock("/b"))


class ReviewNow(ParallelReviews):
    """pr-reviewer.py REPO N: 큐에 넣고 폴링이 가져간다."""

    def ask(self, repo: str, n: int):
        self.m.QUEUE.mkdir(parents=True, exist_ok=True)
        (self.m.QUEUE / f"{repo}#{n}").write_text("x")

    def test_이미_리뷰한_PR_도_요청하면_다시_리뷰한다(self):
        self.state["repos"]["app"]["prs"] = {str(n): {"reviewed_at": "old", "session_id": "s"} for n in (1, 2, 3)}
        self.state["repos"]["app"]["prs"]["2"]["gave_up"] = "x"
        self.ask("app", 2)
        self.m.poll_locked(self.cfg, self.state)
        ps = self.state["repos"]["app"]["prs"]["2"]
        self.assertEqual((ps["reviewed_at"], ps.get("gave_up")), ("done", None))
        self.assertEqual(self.state["repos"]["app"]["prs"]["1"]["reviewed_at"], "old")
        self.assertEqual(self.m.queued(), set())

    def test_auto_review_가_꺼져도_요청한_PR_은_리뷰한다(self):
        self.cfg["auto_review"] = False
        self.ask("app", 3)
        self.m.poll_locked(self.cfg, self.state)
        self.assertEqual(self.state["repos"]["app"]["prs"]["3"]["reviewed_at"], "done")
        self.assertNotIn("reviewed_at", self.state["repos"]["app"]["prs"]["1"])

    def test_닫힌_PR_과_모르는_레포_요청은_버린다(self):
        self.state["repos"]["app"]["prs"] = {str(n): {"reviewed_at": "old"} for n in (1, 2, 3)}
        self.ask("app", 99)
        self.ask("nope", 1)
        self.m.poll_locked(self.cfg, self.state)
        self.assertEqual(self.m.queued(), set())
        self.assertEqual(self.peak, 0)

    def test_처음_보는_레포여도_요청한_PR_은_리뷰한다(self):
        self.state = {}
        self.ask("app", 1)
        self.m.poll_locked(self.cfg, self.state)
        prs = self.state["repos"]["app"]["prs"]
        self.assertEqual(prs["1"]["reviewed_at"], "done")
        self.assertNotIn("reviewed_at", prs["2"])

    def test_명령은_큐에_넣고_launchd_가_없으면_바로_돈다(self):
        ran = []
        self.m.poll = lambda: ran.append(sorted(self.m.queued())) or 0
        self.assertEqual(self.m.review_now("app", 7), 0)
        self.assertEqual(ran, [[("app", 7)]])
        self.assertEqual(self.m.review_now("nope", 7), 1)


class Terminals(Base):
    def setUp(self):
        super().setUp()
        self.m.ORCA_APP = str(self.home / "no-orca")
        self.m.GHOSTTY_APPS = [self.home / "Ghostty.app"]
        self.m.find_tool = lambda paths, name: None  # PATH 에 있는 orca 를 찾지 않게
        self.calls = []

    def fake_osascript(self, *answers: str):
        it = iter(answers)

        def tcall(cfg, argv):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, next(it) + "\n", "")
        self.m.tcall = tcall

    def test_auto_는_Orca_다음_Ghostty_다음_none(self):
        self.assertEqual(self.config(repos={}, terminal="auto")["terminal"], "none")
        (self.home / "Ghostty.app").mkdir()
        self.assertEqual(self.config(repos={}, terminal="auto")["terminal"], "ghostty")
        Path(self.m.ORCA_APP).write_text("")
        self.assertEqual(self.config(repos={}, terminal="auto")["terminal"], "orca")
        self.assertEqual(self.config(repos={}, terminal="ghostty")["terminal"], "ghostty")
        self.assertEqual(self.config(repos={}, terminal="auto")["terminal_setting"], "auto")

    def test_Ghostty_에_그_폴더_탭이_있으면_그리로_간다(self):
        cfg = self.config(repos={}, terminal="ghostty")
        self.fake_osascript("focused")
        self.assertTrue(self.m.open_in_terminal(cfg, Path("/wt/app-1"), "claude --resume s", "app#1"))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][-2:], ["--", "/wt/app-1"])

    def test_Ghostty_에_탭이_없으면_새_탭에서_명령을_실행한다(self):
        cfg = self.config(repos={}, terminal="ghostty")
        self.fake_osascript("none", "opened")
        self.assertTrue(self.m.open_in_terminal(cfg, Path("/wt/app-1"), "claude --resume s", "app#1"))
        self.assertEqual(self.calls[1][0], "/usr/bin/osascript")
        self.assertEqual(self.calls[1][-4:], ["--", "/wt/app-1", "claude --resume s", "app#1"])
        self.assertIn("new tab in front window", self.calls[1][2])

    def test_Ghostty_가_막히면_False(self):
        cfg = self.config(repos={}, terminal="ghostty")
        self.m.tcall = lambda cfg, argv: subprocess.CompletedProcess(argv, 1, "", "not allowed")
        self.assertFalse(self.m.open_in_terminal(cfg, Path("/wt"), "c", "t"))

    def test_Ghostty_탭에는_답글을_넣지_않는다(self):
        cfg = self.config(repos={}, terminal="ghostty")
        self.assertIs(self.m.terminal_send(cfg, Path("/wt"), "x"), False)

    def test_Ghostty_는_git_worktree_에서_작업_폴더를_찾는다(self):
        cfg = self.config(repos={}, terminal="ghostty")
        listing = (f"worktree /w/app\nHEAD 1\nbranch refs/heads/main\n\n"
                   f"worktree {self.m.WORKTREES}/app-3\nHEAD 2\nbranch refs/heads/feature/x\n\n"
                   f"worktree /w/app-x\nHEAD 2\nbranch refs/heads/feature/x\n")
        self.m.git = lambda cfg, *a, cwd, **k: subprocess.CompletedProcess(a, 0, listing, "")
        self.assertEqual(self.m.work_tree_for_branch(cfg, "/w/app", "feature/x"), "/w/app-x")
        self.assertIsNone(self.m.work_tree_for_branch(cfg, "/w/app", "nope"))


class OrcaDetails(Base):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(repos={"app": "/w/app"}, terminal="orca")
        self.calls, self.tabs = [], []
        m = self.m
        m.orca = lambda cfg, *args: self.calls.append(list(args)) or ({"terminals": self.tabs} if "list" in args else {})
        m.git = lambda cfg, *a, cwd, **k: subprocess.CompletedProcess(a, 0, "origin/main\n", "")
        m.orca_worktree_for_branch = lambda cfg, repo_dir, branch: "/w/app" if branch == "main" else None

    def sets(self):
        return [c for c in self.calls if c[:2] == ["worktree", "set"]]

    def test_리뷰가_끝나면_이름_상태_unread_를_맞추고_탭을_연다(self):
        self.m.terminal_prepare(self.cfg, Path("/wt/app-7"), "sid", "app#7", "/w/app", "main", 7, "feat: 결제 완료 화면 안내 문구 수정")
        nest, unread = self.sets()
        self.assertEqual(nest[nest.index("--display-name") + 1], "리뷰 #7 feat: 결제 완료 화면 안내 문구 수정")
        self.assertEqual(nest[nest.index("--workspace-status") + 1], "in-review")
        self.assertEqual(nest[nest.index("--parent-worktree") + 1], "path:/w/app")
        self.assertIn("--unread", unread)
        self.assertTrue(any(c[:2] == ["terminal", "create"] for c in self.calls))

    def test_긴_제목은_줄인다(self):
        name = self.m.review_display_name(7, "가" * 100)
        self.assertEqual(len(name), len("리뷰 #7 ") + self.m.ORCA_TITLE_MAX)
        self.assertTrue(name.endswith("…"))

    def test_orca_sync_는_남은_리뷰_worktree_를_다시_맞춘다(self):
        for n in (1, 2):
            self.m.worktree_path("app", n).mkdir(parents=True)
        self.m.write_json(self.m.STATE, {"repos": {"app": {"prs": {"1": {"title": "옛 제목"}, "2": {}, "3": {}}},
                                                   "gone": {"prs": {"1": {}}}}})
        self.m.write_json(self.m.STATUS, {"prs": [{"repo": "app", "number": 2, "title": "새 제목"}]})
        self.assertEqual(self.m.orca_sync(), 0)
        names = sorted(c[c.index("--display-name") + 1] for c in self.sets())
        self.assertEqual(names, ["리뷰 #1 옛 제목", "리뷰 #2 새 제목"])

    def test_orca_가_아니면_orca_sync_는_실패(self):
        self.config(repos={}, terminal="none")
        self.assertEqual(self.m.orca_sync(), 1)


class OrcaReplyUnread(ReplyBase):
    def test_답글_리뷰가_끝나면_unread(self):
        self.cfg = self.config(repos={"app": str(self.home)}, terminal="orca")
        marks = []
        self.m.orca_mark_unread = lambda cfg, wt: marks.append(wt)
        self.issue = [rc(10, "me", "2026-01-01T00:00:00Z"), rc(11, "alice", "2026-01-02T00:00:00Z")]
        self.m.check_replies(self.cfg, self.state, "me", "app", "/repo", self.pr)
        self.assertEqual(marks, [self.m.worktree_path("app", 1)])


class Version(Base):
    def test_스크립트_VERSION_은_플러그인_버전과_같다(self):
        manifest = SCRIPT.parents[1] / ".claude-plugin" / "plugin.json"
        self.assertEqual(self.m.VERSION, json.loads(manifest.read_text())["version"])


class Ops(Base):
    """/pr-action-bar 가 부르는 운영 명령."""

    def out(self, fn, *args) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = fn(*args)
        return code, buf.getvalue()

    def git_repo(self, name: str) -> Path:
        d = self.home / name
        d.mkdir()
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        return d

    def test_init_은_대화_없이_설정을_만들고_합친다(self):
        a, b = self.git_repo("a"), self.git_repo("b")
        code, _ = self.out(self.m.init_config, [f"app={a}"], False, "ghostty")
        self.assertEqual(code, 0)
        cfg = json.loads(self.m.CONFIG.read_text())
        self.assertEqual((list(cfg["repos"]), cfg["auto_review"], cfg["terminal"]), (["app"], False, "ghostty"))
        self.assertEqual(Path(cfg["repos"]["app"]).resolve(), a.resolve())
        self.out(self.m.init_config, [f"api={b}"], None, None)
        cfg = json.loads(self.m.CONFIG.read_text())
        self.assertEqual((sorted(cfg["repos"]), cfg["auto_review"]), (["api", "app"], False))

    def test_init_은_잘못된_값을_거절한다(self):
        self.assertEqual(self.out(self.m.init_config, ["앱=/tmp"], None, None)[0], 1)
        self.assertEqual(self.out(self.m.init_config, [f"app={self.home}/nope"], None, None)[0], 1)
        self.assertEqual(self.out(self.m.init_config, [], None, "iterm")[0], 1)
        self.assertFalse(self.m.CONFIG.exists())

    def test_flicker_는_두_곳에_한_번만_넣는다(self):
        settings, rc = self.home / "settings.json", self.home / ".zshrc"
        settings.write_text('{"model": "opus"}')
        rc.write_text("alias ll='ls -l'")
        for _ in range(2):
            self.assertEqual(self.out(self.m.flicker, settings, rc)[0], 0)
        self.assertEqual(json.loads(settings.read_text()), {"model": "opus", "env": {"CLAUDE_CODE_NO_FLICKER": "1"}})
        self.assertEqual(rc.read_text().count(self.m.FLICKER_LINE), 1)
        self.assertTrue(rc.read_text().startswith("alias ll='ls -l'\n"))

    def test_prompts_는_기본값을_꺼내고_내_파일은_건드리지_않는다(self):
        self.m.PROMPTS.mkdir(parents=True)
        (self.m.PROMPTS / "reply.md").write_text("내 답글 프롬프트")
        code, text = self.out(self.m.export_prompts)
        self.assertEqual(code, 0)
        self.assertTrue((self.m.PROMPTS / "defaults" / "summarize.md").exists())
        self.assertTrue((self.m.PROMPTS / "defaults" / "FORMAT.md").exists())
        self.assertEqual((self.m.PROMPTS / "reply.md").read_text(), "내 답글 프롬프트")
        self.assertIn("내 파일 사용", text)

    def test_status_는_버전_차이와_멈춘_PR_을_보여_준다(self):
        self.config(repos={"app": "/w/app"})
        self.m.launchd_loaded = lambda: True
        self.m.write_json(self.m.STATUS, {"version": "0.1.0", "updated_at": "t", "failed_repos": ["app"]})
        self.m.write_json(self.m.STATE, {"repos": {"app": {"prs": {"3": {"gave_up": "x", "last_error": "boom"}}}}})
        code, text = self.out(self.m.status_report)
        self.assertEqual(code, 0)
        for word in (f"이 스크립트 {self.m.VERSION} · 설치본 0.1.0", "update 필요", "조회 실패: app", "app#3 (boom)"):
            self.assertIn(word, text)

    def test_update_는_설정이_있어야_하고_설치_뒤_버전을_알린다(self):
        self.assertEqual(self.out(self.m.update)[0], 1)
        self.config(repos={})
        self.m.write_json(self.m.STATUS, {"version": "0.1.0"})
        self.m.install = lambda: 0
        code, text = self.out(self.m.update)
        self.assertEqual(code, 0)
        self.assertIn(f"0.1.0 → {self.m.VERSION}", text)

    def test_명령줄로_부른다(self):
        a = self.git_repo("a")
        argv = sys.argv
        try:
            sys.argv = ["pr-reviewer.py", "--init", "--repo", f"app={a}", "--auto-review", "off"]
            self.assertEqual(self.out(self.m.main)[0], 0)
            sys.argv = ["pr-reviewer.py", "preflight"]
            self.m.doctor = lambda: []
            self.assertEqual(self.out(self.m.main), (0, "문제 없음\n"))
        finally:
            sys.argv = argv
        self.assertFalse(json.loads(self.m.CONFIG.read_text())["auto_review"])

    def test_terminal_진단_none(self):
        self.config(repos={}, terminal="none")
        code, text = self.out(self.m.terminal_check)
        self.assertEqual(code, 0)
        self.assertIn("PR 페이지가 열린다", text)


def re_find_path(text: str) -> str:
    import re
    return re.search(r"(/\S+\.md)", text).group(1)


if __name__ == "__main__":
    unittest.main()
