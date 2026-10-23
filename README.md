# pr-action-bar

PR 상태를 Slack 알림 대신 **Claude Code 입력창 바로 위**에 띄우고, 새 PR 은 내 맥에서 `/code-review` 로 미리 리뷰해 두는 도구 두 개.

```text
* My PR    [ Awaiting re-review repo-a#1234 ]  [ Awaiting approval repo-b#562 ]
* Team PR  [ Needs review repo-a#1235 ]  [ Re-review repo-c#87 ]
* This PR  [ Needs review ]  feat: 결제 완료 화면 안내 문구 수정 (#1235)  [ SHOP-482 ]  리뷰 파일
```

- **pr-reviewer** (`pr-reviewer/pr-reviewer.py`): launchd 로 5분마다 돈다. 처음 보는 PR 을 PR 전용 git worktree 에서 헤드리스 Claude Code 로 리뷰하고(`/code-review` → 재검토 → 정리), 내 코멘트 스레드에 달린 답글도 리뷰해 둔다. 끝나면 열린 PR 상태를 `~/.pr-reviewer/status.json` 에 쓴다.
- **review-buttons** (`review-buttons/`): 그 파일을 30초마다 읽어 입력창 위 띠로 보여 주는 Claude Code mod. PR 을 누르면 상태에 맞는 곳(리뷰 세션 탭·작업하던 탭·PR 페이지)으로 간다.

만든 이유와 설계는 블로그 글에 있다: [Claude Code Mod로 PR 상태 관리하고 리뷰까지 자동화하기](https://keh7264.github.io/blog/claude-code-pr-action-bar/)

> 봇은 리뷰를 **게시하지 않는다**. 리뷰 파일에서 코멘트를 복사해 붙이거나, 리뷰 세션 탭에서 직접 시킨다. 리뷰 실행은 읽기 전용 도구만 허용한다.

## 요구 사항

- macOS (launchd, `caffeinate`, `open` 을 쓴다)
- Python 3.10+ (표준 라이브러리만 쓴다), git, [GitHub CLI](https://cli.github.com/) 로그인(`gh auth login`)
- [Claude Code](https://claude.com/claude-code) — `/code-review` 스킬과 mod(hooks module)를 지원하는 버전
- 선택: `terminal-notifier` (알림 클릭으로 PR 열기), Orca (리뷰 세션 탭)

## 두 가지 쓰는 법

| | 띠만 쓰기 | 띠 + 자동 리뷰 |
|---|---|---|
| 설정 | `"auto_review": false` | `"auto_review": true` (기본값) |
| 하는 일 | 5분마다 GitHub 상태만 받아 띠에 띄운다 | 그에 더해 새 PR 을 미리 리뷰하고 답글도 리뷰해 둔다 |
| 필요한 것 | python3, git, gh | 그에 더해 claude (`/code-review`) |
| Claude 사용량 | 없음 | PR 마다 리뷰 1회 + 답글 |
| PR 을 누르면 | 내 PR 은 작업하던 탭(`terminal: orca`) 또는 PR 페이지, 남의 PR 은 PR 페이지 | 남의 PR 은 `terminal: orca` 면 리뷰 세션 탭, 아니면 PR 페이지 |

어느 쪽이든 GitHub 조회는 폴러 한 곳에서만 하고 mod 는 `status.json` 만 읽는다. 그래서 띠만 쓸 때도 pr-reviewer 를 설치한다. 띠만 쓰는 동안 열린 PR 은 "본 것"으로 기록되므로, 나중에 `auto_review` 를 `true` 로 바꾸면 그때부터 새로 올라오는 PR 만 리뷰한다. 끄는 동안에도 닫힌 PR 의 worktree 정리는 계속 한다.

## 설치

### 1. pr-reviewer

```sh
git clone https://github.com/keh7264/pr-action-bar.git
cd pr-action-bar
python3 pr-reviewer/pr-reviewer.py install   # 처음엔 ~/.pr-reviewer/config.json 만 만들고 멈춘다
$EDITOR ~/.pr-reviewer/config.json            # repos 에 레포의 로컬 경로를 적는다 (띠만 쓰면 auto_review: false)
python3 pr-reviewer/pr-reviewer.py install   # 점검 → 복사 → launchd 등록
```

`install` 이 하는 일:

- `gh`·`git` (자동 리뷰를 쓰면 `claude`·`node` 도) 의 **절대 경로**를 찾아 설정에 적는다. launchd 는 로그인 셸 PATH 를 받지 않아서 nvm·fnm 으로 깐 claude 를 못 찾는다. fnm 이 셸마다 만드는 임시 경로(`fnm_multishells/…`)는 기본 버전 경로로 바꿔 적는다.
- 점검: 각 도구 실행, `gh auth status`, 레포마다 비밀번호 없이 `git ls-remote`(타임아웃 15초, VPN 확인용).
- 스크립트를 `~/.pr-reviewer/bin/` 에 복사해 두고 launchd 는 그 복사본을 실행한다. 레포를 업데이트한 뒤에는 `install` 을 다시 돌린다.
- 리뷰가 도는 중이면 launchd 등록 변경을 미룬다.

처음 보는 레포는 **지금 열린 PR 을 "본 것"으로만 기록**한다. 설치 직후 수십 개 PR 을 한꺼번에 리뷰해 사용량이 터지지 않게 하려는 것이다. 그 뒤에 올라오는 PR 부터 자동 리뷰한다.

### 2. review-buttons (띠)

```sh
claude plugin marketplace add keh7264/pr-action-bar
claude plugin install review-buttons@pr-action-bar
```

띠를 마우스로 누르려면 Claude Code 를 전체화면 모드로 실행한다: `CLAUDE_CODE_NO_FLICKER=1 claude`. 아니면 띠에 안내가 뜬다.

## 설정 (`~/.pr-reviewer/config.json`)

| 키 | 기본값 | 설명 |
|---|---|---|
| `auto_review` | `true` | `false` 면 띠만 쓴다. 리뷰·worktree·답글 리뷰를 하지 않는다 |
| `repos` | `{}` | `{"짧은이름": "로컬 경로"}`. 짧은 이름이 띠에 `repo-a#1234` 처럼 붙는다 |
| `effort` | `high` | `/code-review` 에 넘길 레벨 |
| `timeout_minutes` | `40` | 리뷰 한 단계의 시간 제한 |
| `max_attempts` | `2` | 같은 커밋 N 회, PR 전체 2N 회 실패하면 그 PR 은 자동 리뷰를 멈추고 알린다 |
| `skip_authors` | `[]` | 리뷰하지 않을 작성자 (내 PR 은 항상 건너뛴다) |
| `bot_pr_markers` | `[]` | 내가 만든 봇이 연 PR 의 제목 표시. My PR 로 보고 "내가 고칠 수정 목록" 형태로 리뷰한다 |
| `release_pr_authors`, `release_pr_title_pattern` | | CI 봇이 여는 릴리스 머지 PR. 리뷰하지 않고 왜 막혔는지만 띄운다 |
| `pause_minutes` | `30` | 사용 한도·네트워크·로그인 문제일 때 전체 리뷰를 쉬는 시간 |
| `notify_every_hours` | `3` | 같은 종류의 "쉬는 중" 알림 간격 |
| `terminal` | `none` | `none` · `orca` (아래 참고) |
| `language` | `ko` | 리뷰 정리 언어 |
| `issue_url_template` | `""` | This PR 줄의 이슈 링크. 예: `https://your-team.atlassian.net/browse/{key}` |

### 프롬프트 바꾸기

`~/.pr-reviewer/prompts/<이름>.md` 를 두면 기본 프롬프트 대신 쓴다. 이 폴더는 업데이트가 건드리지 않는다.

- `review`, `recheck`, `recheck_bot`, `summarize`, `summarize_bot`, `reply`
- `extra-criteria.md`: 재검토 단계에 덧붙일 팀 리뷰 기준
- 자리표시자는 `{{NUMBER}}`, `{{EFFORT}}`, `{{LANGUAGE}}`, `{{THREAD_FILE}}`, `{{EXTRA_CRITERIA}}`. 문자열 치환이라 JSON 예시의 `{ }` 를 그대로 써도 된다.

`summarize` 의 출력 형식(`summary` + `findings[]`)은 바꾸지 않는 게 좋다. 형식이 깨져 오면 리뷰를 버리지 않고 원문을 그대로 리뷰 파일에 남긴다.

## 띠의 상태

PR 하나에 상태는 하나. 위에서부터 먼저 걸리는 것이다.

**Team PR** — Re-review(내 스레드에 남이 마지막으로 답함) → Approved → Updated(답 없이 코드 커밋만 옴, base 머지 커밋 제외) → Awaiting changes → Approved by others → Reviewing(자동 리뷰 중) → Needs review

**My PR** — Reply → Resolve conflicts → Fix CI → Awaiting re-review → Address changes → Awaiting approval → CI running → Merge, 그리고 Draft. 릴리스 머지 PR 은 Resolve conflicts / Fix CI / CI running / Check merge.

PR 번호에 마우스를 올리면 주황(Claude 세션이 열림) 또는 흰색(브라우저가 열림)으로 표시된다. 이 판정은 봇이 상태를 계산할 때 한 번 해서 `status.json` 의 `opens` 에 넣고, hover 색과 실제 클릭이 같은 값을 쓴다.

## 터미널 연동

| `terminal` | 리뷰가 끝나면 | PR 을 누르면 |
|---|---|---|
| `none` | 알림만 | PR 페이지 |
| `orca` | 그 PR worktree 에 `claude --resume` 탭을 포커스 없이 열어 둔다 | 그 탭으로 이동, 닫혔으면 세션을 이어 새로 연다 |

터미널 앱 호출에는 짧은 타임아웃(`terminal_timeout_seconds`)이 있어서 앱이 응답하지 않아도 폴러와 띠 클릭이 멈추지 않는다.

답글이 달리면 열린 리뷰 탭의 **입력창이 비어 있을 때만** 프롬프트를 한 줄로 합쳐 보낸다. 쓰다 만 글이 있으면 다음 폴링으로 미룬다. 탭이 없으면 원래 세션을 갈라서(`--fork-session`) 헤드리스로 돌린다.

> **Orca 주의**: `orca terminal create --worktree path:<경로>` 는 Orca 가 아는 worktree 여야 한다. 리뷰 worktree(`~/.pr-reviewer/wt/…`)가 Orca 에 등록돼 있지 않으면 탭 열기가 실패하고 PR 페이지로 대신 연다.

## 이렇게 버틴다

블로그 글의 뼈대에 더해 다른 사람 맥에서도, 실패해도, 사람이 같이 써도 망가지지 않게 넣은 것들:

- **실패 처리**: 사용 한도·네트워크·로그인 실패는 PR 하나가 아니라 전체 문제로 보고 30분 쉰다(재시도 횟수에 넣지 않음). 분류는 claude 결과의 오류 필드와 git/gh stderr 만 본다. 같은 PR 에서 일시적 실패가 3번 이어지면 그때는 실패로 센다. 리뷰 결과는 알림·터미널 작업보다 먼저 저장한다. 리뷰 직전에 PR 을 다시 조회한다(닫힘·Draft·새 커밋). 리뷰하는 동안 `caffeinate -i -w` 로 잠자기를 막는다. 락을 못 잡은 실행도 `status.json` 은 갱신한다.
- **worktree 보호**: 체크아웃 전에 사용자 작업(브랜치 체크아웃, 바뀐 파일, PR 에 없는 커밋)을 확인하고 있으면 보류한다. force-push 오인을 막으려고 지난번 체크아웃한 커밋도 기준에 넣는다. 깨진 worktree 는 옆으로 비켜 두고 새로 만든다. 열린 PR 목록이 조회 상한(100)에 닿으면 정리를 건너뛴다.
- **답글 리뷰**: 기준점은 리뷰를 시작할 때 잡는다. 봇 계정 답글은 뺀다. 일시적으로 실패하면 그 답글을 본 것으로 넘기지 않는다.
- **권한**: 스킬은 `Skill(code-review)` 하나만, 출력을 거르는 `head`·`tail`·`wc`·`cut`·`tr` 은 허용, `sed -i`·`sort -o`·`git fetch`·`rg` 는 뺐다. 허용 규칙은 접두사만 보므로 `Bash(*--output*)` 같은 차단 규칙을 따로 둔다. 개인 hook 은 끈다(`disableAllHooks`).
- **띠**: 헤드리스 세션에서는 아무것도 하지 않는다. `status.json` 이 없으면 띠를 비우고, 읽기 실패면 직전 값을 유지한다. 값이 바뀌었을 때만 다시 그린다. 클릭 명령에 타임아웃을 두고 실패하면 stderr 마지막 줄을 토스트로 띄운다. 같은 자리를 쓰는 다른 mod 의 띠도 함께 그린다.

## 명령

```sh
python3 ~/.pr-reviewer/bin/pr-reviewer.py              # 정규 폴링 1회
python3 ~/.pr-reviewer/bin/pr-reviewer.py --refresh     # status.json 즉시 갱신 (--full: 정규 폴링도 kickstart)
python3 ~/.pr-reviewer/bin/pr-reviewer.py --open repo-a 1235 [--mine]
python3 ~/.pr-reviewer/bin/pr-reviewer.py doctor        # 설치 점검만
python3 ~/.pr-reviewer/bin/pr-reviewer.py uninstall     # launchd 해제 (기록·worktree 는 남는다)
```

로그: `~/.pr-reviewer/logs/pr-reviewer.log` · 리뷰 파일: `~/.pr-reviewer/reviews/<repo>/<번호>-<커밋>.md`

## 라이선스

MIT
