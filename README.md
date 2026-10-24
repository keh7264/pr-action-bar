# pr-action-bar

PR 상태를 Slack 알림 대신 Claude Code 입력창 바로 위에 띄우고, 새 PR은 내 맥에서 `/code-review`로 미리 리뷰해 두는 도구다.

```text
* My PR    [ Awaiting re-review repo-a#1234 ]  [ Awaiting approval repo-b#562 ]
* Team PR  [ Needs review repo-a#1235 ]  [ Re-review repo-c#87 ]
* This PR  [ Needs review ]  feat: 결제 완료 화면 안내 문구 수정 (#1235)  [ SHOP-482 ]  리뷰 파일
```

레포 여러 개를 오가며 리뷰하다 보면 PR마다 상태가 다 다르다. 답글이 달린 것, 승인은 받았는데 스레드가 안 닫혀 머지가 막힌 것, 리뷰를 읽어만 두고 코멘트를 안 단 것. 이런 변화가 Slack 알림으로 오긴 하는데 다른 메시지에 섞여 지나가 버려서, 결국 PR 목록을 수시로 열어 보게 됐다. 하루 대부분을 Claude Code를 띄워 놓고 일하니까 차라리 거기에 띄우자고 생각해서 만들었다.

자세한 이야기는 블로그에 써 뒀다: [Claude Code Mod로 PR 상태 관리하고 리뷰까지 자동화하기](https://keh7264.github.io/blog/claude-code-pr-action-bar/)

두 부분으로 되어 있다.

- `pr-reviewer/`: launchd로 5분마다 도는 파이썬 스크립트다. 열린 PR 상태를 `~/.pr-reviewer/status.json`에 써 두고, 새 PR이 보이면 PR 전용 worktree에서 헤드리스 Claude Code로 리뷰를 돌린다. 내 리뷰 코멘트에 답글이 달려도 다시 봐 둔다.
- `review-buttons/`: 그 파일을 30초마다 읽어서 입력창 위에 띠로 그리는 Claude Code mod다. PR 번호를 누르면 리뷰 세션 탭이나 작업하던 탭, 아니면 PR 페이지로 간다.

리뷰는 PR에 올리지 않는다. 어떤 코멘트를 달지는 내가 정하고 싶어서다. 리뷰 파일에서 복사해 붙이거나, 리뷰 세션 탭에서 같이 보고 "이거 달아 줘"라고 시키면 된다. 그래서 리뷰를 돌릴 때는 읽기 전용 도구만 허용한다.

## 필요한 것

- macOS (launchd, `caffeinate`, `open`을 쓴다)
- Python 3.10 이상, git, 로그인된 [GitHub CLI](https://cli.github.com/) (`gh auth login`)
- [Claude Code](https://claude.com/claude-code). mod를 지원하는 버전이어야 하고, 자동 리뷰를 쓰면 `/code-review` 스킬도 있어야 한다
- 있으면 좋은 것: `terminal-notifier` (알림을 누르면 PR이 열린다. `setup`이 brew로 깔아 준다), Orca (리뷰 세션을 탭으로 연다)

## 띠만 쓸 수도 있다

리뷰는 필요 없고 상태만 보고 싶으면 설정에서 `"auto_review": false`로 두면 된다. 그러면 GitHub 상태만 받아서 띠에 띄우고 리뷰는 돌리지 않으니, 리뷰에 드는 Claude 사용량이 없다. 띠는 Claude Code 안에 그려지는 거라 Claude Code는 당연히 있어야 한다.

이때도 pr-reviewer는 설치해야 한다. GitHub 조회는 pr-reviewer 한 곳에서만 하고 mod는 `status.json`만 읽기 때문이다. 띠만 쓰는 동안 열린 PR은 "본 것"으로 기록해 두니까, 나중에 `auto_review`를 켜도 밀린 PR을 한꺼번에 리뷰하지 않고 그 뒤에 올라온 PR부터 리뷰한다.

## 설치

### pr-reviewer

```sh
git clone https://github.com/keh7264/pr-action-bar.git
cd pr-action-bar
python3 pr-reviewer/pr-reviewer.py setup
```

`setup`이 차례로 묻는다.

1. 리뷰할 레포. Orca에 등록된 레포가 있으면 번호로 고르고, 없으면 경로를 적는다. 띠에 붙을 짧은 이름도 정한다.
2. 자동 리뷰를 쓸지. 끄면 띠만 쓴다. 켜면 `/code-review high`(설정의 `effort`, 기본 high)로 리뷰하고, 지적마다 실제로 터지는지 한 번 더 검증한 뒤에 알린다.
3. PR을 누르면 Orca 탭으로 갈지. 그러면 레포를 Orca에 등록하고 바깥 worktree도 보이게 켜 둔다.
4. `terminal-notifier`가 없으면 brew로 설치할지. 있어야 알림을 눌러 PR을 연다. 없으면 맥 기본 알림만 뜬다.
5. 이슈 링크 템플릿과 이슈 프로젝트 키.

다 답하면 `~/.pr-reviewer/config.json`에 저장하고 바로 설치까지 한다. 다시 돌리면 지금 값을 기본값으로 묻는다. 나머지 값(`skip_authors`, `bot_pr_markers` 등)은 그 파일을 직접 고친다. 설정만 고친 뒤에는 `install`로 다시 설치한다.

`install`은 `gh`, `git`, `claude` 같은 도구의 절대 경로를 찾아 설정에 적어 둔다. launchd는 로그인 셸의 PATH를 모르기 때문에, nvm이나 fnm으로 깐 claude를 이렇게 안 해 주면 못 찾는다. 그다음 도구들이 실제로 돌아가는지, `gh`가 로그인돼 있는지, 레포마다 비밀번호 없이 `git ls-remote`가 되는지(VPN이 필요한 회사 레포 때문에) 확인한다. 스크립트는 `~/.pr-reviewer/bin/`에 복사해 두고 launchd는 그 복사본을 돌린다. 그래서 레포를 업데이트하면 `install`을 한 번 더 돌려야 한다.

처음 보는 레포에 이미 열려 있던 PR은 리뷰하지 않는다. 설치하자마자 PR 수십 개를 한 번에 리뷰해서 사용량이 바닥나는 걸 막으려고 그렇게 했다.

### review-buttons

```sh
claude plugin marketplace add keh7264/pr-action-bar
claude plugin install review-buttons@pr-action-bar
```

띠를 마우스로 누르려면 Claude Code를 `CLAUDE_CODE_NO_FLICKER=1 claude`로 켜야 한다. 그냥 켜면 띠는 보이지만 클릭이 안 되고, 띠에 그렇다고 안내가 뜬다.

## 설정

`~/.pr-reviewer/config.json`

| 키 | 기본값 | 설명 |
|---|---|---|
| `auto_review` | `true` | `false`면 띠만 쓴다 |
| `repos` | `{}` | `{"짧은이름": "로컬 경로"}`. 짧은 이름이 띠에 `repo-a#1234`처럼 붙는다 |
| `effort` | `high` | `/code-review`에 넘길 레벨 |
| `timeout_minutes` | `40` | 리뷰 한 단계에 쓸 수 있는 시간 |
| `max_attempts` | `2` | 같은 커밋에서 이만큼 실패하면 그 PR은 자동 리뷰를 멈추고 알려 준다 |
| `skip_authors` | `[]` | 리뷰하지 않을 작성자. 내 PR은 원래 리뷰하지 않는다 |
| `bot_pr_markers` | `[]` | 내가 돌리는 봇이 연 PR의 제목 표시. 내 PR로 치고, 리뷰도 "내가 고칠 목록" 모양으로 정리한다 |
| `release_pr_authors`, `release_pr_title_pattern` | | CI가 여는 릴리스 머지 PR. 리뷰하지 않고 왜 막혔는지만 보여 준다 |
| `pause_minutes` | `30` | 사용 한도, 네트워크, 로그인 문제로 실패했을 때 리뷰를 쉬는 시간 |
| `notify_every_hours` | `3` | 같은 "쉬는 중" 알림을 다시 보내는 간격 |
| `terminal` | `none` | `none` 또는 `orca` |
| `language` | `ko` | 리뷰를 정리할 언어 |
| `issue_url_template` | `""` | This PR 줄의 이슈 링크. 예: `https://your-team.atlassian.net/browse/{key}`. 비워 두면 이슈 버튼이 안 나온다 |
| `issue_projects` | `[]` | 이슈 키로 칠 프로젝트, 예: `["SHOP"]`. 비워 두면 `ABC-123` 모양은 다 잡아서 `UTF-8` 같은 것도 걸릴 수 있으니 적어 두는 게 좋다 |

### 프롬프트를 바꾸고 싶으면

`~/.pr-reviewer/prompts/<이름>.md`에 파일을 두면 기본 프롬프트 대신 그걸 쓴다. 이름은 `review`, `recheck`, `recheck_bot`, `summarize`, `summarize_bot`, `reply`다. 팀 리뷰 기준만 덧붙이고 싶으면 `extra-criteria.md`에 적으면 재검토 단계에 들어간다.

프롬프트 안에서는 `{{NUMBER}}`, `{{EFFORT}}`, `{{LANGUAGE}}`, `{{THREAD_FILE}}`, `{{EXTRA_CRITERIA}}`, `{{FORMAT}}`을 쓸 수 있다. `summarize`가 내는 마크다운은 리뷰 탭에서 그대로 읽히고 리뷰 파일 본문이 된다. 지적마다 붙는 `` `경로:줄` · 꼭 수정 `` 줄로 리뷰 파일 머리의 개수를 세니, 바꾸더라도 `{{FORMAT}}`은 남겨 두는 게 좋다.

## 띠 읽는 법

띠는 세 줄이다.

- My PR: 내가 올린 PR 중에 지금 내가 뭘 해야 하는지. 답글을 달아야 하는지, CI를 고쳐야 하는지, 머지하면 되는지 같은 것.
- Team PR: 남이 올린 PR 중에 내가 봐야 하는 것. 리뷰가 필요한지, 내 코멘트에 답이 왔는지 같은 것.
- This PR: 지금 이 Claude Code 세션이 열린 worktree가 어떤 PR과 연결돼 있는지. 브랜치로 PR을 찾아서 그 PR의 상태, 제목, 이슈 링크, 리뷰 파일을 한 줄로 보여 준다. 리뷰 worktree에서 열었으면 그 리뷰 중인 PR이 뜬다. 연결된 PR이 없으면 이 줄은 안 나온다.

괄호 하나가 상태 하나고, 그 안에 그 상태인 PR 번호들이 들어간다. 위쪽 ↻ 옆의 시각은 마지막으로 갱신한 시간이고, 누르면 바로 다시 받아 온다.

## 띠에 뜨는 상태

PR 하나에는 상태가 하나만 붙는다. 아래 순서대로 먼저 맞는 게 붙는다.

남의 PR: Re-review (내 스레드에 상대가 마지막으로 답했다) → Approved → Updated (답은 없고 커밋만 새로 왔다) → Awaiting changes → Approved by others → Reviewing (지금 리뷰 중) → Needs review

내 PR: Reply → Resolve conflicts → Fix CI → Awaiting re-review → Address changes → Awaiting approval → CI running → Merge, 그리고 Draft. 릴리스 머지 PR은 Resolve conflicts, Fix CI, CI running, Check merge 중 하나다.

PR 번호에 마우스를 올렸을 때 주황색이면 Claude 세션이 열리고, 흰색이면 브라우저가 열린다.

## Orca를 쓴다면

`"terminal": "orca"`로 두면 리뷰가 끝날 때 그 PR worktree에 `claude --resume` 탭을 하나 열어 두고, 띠에서 PR을 누르면 그 탭으로 간다. 탭을 닫았으면 같은 세션을 이어서 다시 연다.

리뷰 worktree(`~/.pr-reviewer/wt/…`)는 Orca가 만든 게 아니라서 그냥 두면 Orca가 모른다. 그러면 탭을 못 열고 PR 페이지가 대신 열린다. `setup`에서 Orca를 고르면 레포를 Orca에 등록하고 바깥 worktree도 보이게 켜 준다. 손으로 하려면 이렇게 한다.

```sh
orca repo add --path ~/work/app
orca repo set --repo path:$HOME/work/app --external-worktree-visibility show
```

리뷰 worktree는 Orca 사이드바에서 그 레포의 기본 브랜치 worktree 아래에 `#1235 리뷰` 같은 이름으로 들어간다. 리뷰 세션이 많아져도 작업하던 worktree와 섞이지 않게 하려고 그렇게 했다. 기본 브랜치를 체크아웃한 worktree가 Orca에 없으면 `repos`에 적은 경로 아래로 넣는다.

리뷰 탭을 처음 열 때 Claude Code가 이 폴더를 믿을지 한 번 물어본다.

내 리뷰에 답글이 달리면, 열려 있는 리뷰 탭의 입력창이 비어 있을 때만 그 탭에 프롬프트를 넣는다. 뭔가 쓰고 있던 중이면 다음 폴링까지 기다린다. 탭이 없으면 원래 세션을 갈라서(`--fork-session`) 뒤에서 돌린다.

## 실패했을 때

다른 사람 맥에서 돌려도, 중간에 실패해도 망가지지 않게 신경 쓴 부분이 있다.

사용 한도나 네트워크, 로그인 문제로 실패하면 PR 하나의 문제가 아니라서 리뷰 전체를 30분 쉬고, 이건 실패 횟수로 세지 않는다. 리뷰하기 직전에는 PR을 한 번 더 조회해서 그사이 닫혔거나 Draft가 됐거나 커밋이 새로 왔는지 본다. 리뷰하는 동안은 맥이 잠들지 않게 하고, 리뷰가 길어져도 띠가 멈춰 보이지 않게 5분마다 상태를 갱신한다.

worktree에 내가 직접 고친 파일이나 다른 브랜치가 있으면 덮어쓰지 않고 그 PR은 건너뛴다. worktree가 깨져 있으면 옆으로 치워 두고 새로 만든다. PR이 닫히면 worktree를 지운다.

띠는 헤드리스 세션에서는 아무것도 안 한다. `status.json`이 없으면 띠를 비우고, 읽다가 실패하면 직전 내용을 그대로 둔다. 버튼을 눌렀는데 실패하면 이유를 토스트로 띄운다.

## 명령

```sh
python3 ~/.pr-reviewer/bin/pr-reviewer.py              # 폴링 한 번
python3 ~/.pr-reviewer/bin/pr-reviewer.py --refresh     # status.json만 바로 갱신 (--full이면 리뷰 폴링도 같이)
python3 ~/.pr-reviewer/bin/pr-reviewer.py --open repo-a 1235 [--mine]
python3 ~/.pr-reviewer/bin/pr-reviewer.py setup         # 설정을 묻고 답하며 다시 고친다
python3 ~/.pr-reviewer/bin/pr-reviewer.py doctor        # 설치 상태만 점검
python3 ~/.pr-reviewer/bin/pr-reviewer.py uninstall     # launchd에서 뺀다 (기록과 worktree는 남는다)
```

로그는 `~/.pr-reviewer/logs/pr-reviewer.log`, 리뷰 파일은 `~/.pr-reviewer/reviews/<repo>/<번호>-<커밋>.md`에 쌓인다.

## 라이선스

MIT
