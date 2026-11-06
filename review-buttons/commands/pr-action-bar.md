---
description: pr-action-bar 설치 · 업데이트 · 점검 (setup, update, status, preflight, prompts, notify, flicker, uninstall)
argument-hint: "[setup|update|status|preflight|prompts|notify|flicker|uninstall]"
---

pr-action-bar(PR 상태 띠와 리뷰 봇)를 관리한다. 하위 명령: `$ARGUMENTS`

봇 스크립트는 이 플러그인 안에 있다.

```sh
SCRIPT="${CLAUDE_PLUGIN_ROOT}/pr-reviewer/pr-reviewer.py"
PY=/usr/bin/python3   # macOS 기본 (3.9 이상). 없으면 python3
```

아래 명령은 모두 이 두 값을 쓴다. 스크립트 출력은 그대로 요약해 보여 주고, 실패하면 출력 마지막 줄과 고칠 방법을 알려 준다.
사용자 파일(설정, launchd, 셸 설정)을 바꾸는 단계는 무엇을 바꾸는지 한 줄로 말한 뒤에 한다.

## 하위 명령

하위 명령이 비어 있으면 `status` 를 돌리고, 결과에 맞는 다음 명령(설치 전이면 `setup`, 버전이 다르면 `update`)을 권한다.

### setup

처음 설치하거나 설정을 다시 할 때.

1. `"$PY" "$SCRIPT" status` 로 지금 상태를 본다. 이미 설정이 있으면 지금 값을 기본값으로 삼는다.
2. 리뷰할 레포를 묻는다. Orca 가 있으면 `orca repo list --json` 의 레포를 후보로 보여 준다. 레포마다 띠에 붙을 짧은 이름(영문 · 숫자 · `-_.`)도 정한다.
3. 자동 리뷰를 쓸지 묻는다. 끄면 띠만 쓰고 Claude 사용량이 들지 않는다.
4. PR 을 누르면 어디로 갈지 묻는다: `auto`(추천, Orca → Ghostty → PR 페이지), `orca`, `ghostty`, `none`.
5. 설정을 쓴다:
   ```sh
   "$PY" "$SCRIPT" --init --repo 이름=경로 [--repo …] --auto-review on|off --terminal-choice auto|orca|ghostty|none
   ```
6. `"$PY" "$SCRIPT" install` 로 점검하고 launchd 에 올린다. 점검에서 나온 문제는 하나씩 풀어 준다 (`gh auth login`, VPN, `xcode-select --install` 등). `terminal-notifier` 가 없으면 `brew install terminal-notifier` 를 권하고, 설치했으면 `install` 을 한 번 더 돌린다.
7. 이어서 `notify` 와 `flicker` 단계를 할지 묻는다.
8. 이슈 링크(`issue_url_template`), `skip_authors`, `bot_logins`, `bot_pr_markers`, `review_instructions` 같은 값은 `~/.pr-reviewer/config.json` 에서 고친다고 알려 준다. 사용자가 원하면 그 파일을 같이 고치고 `install` 을 다시 돌린다.

### update

플러그인을 업데이트한 뒤(`claude plugin update review-buttons@pr-action-bar`) 또는 띠에 "업데이트 필요"가 뜰 때.

```sh
"$PY" "$SCRIPT" update
```

설정은 그대로 두고 설치본(`~/.pr-reviewer/bin/pr-reviewer.py`)과 launchd 를 바꾼다. 리뷰가 도는 중이라 미뤘다고 나오면 잠시 뒤 다시 하라고 알린다.

### status

```sh
"$PY" "$SCRIPT" status
```

버전, launchd, 리뷰 중 · 멈춘 PR, 최근 로그를 요약한다. 문제가 보이면 해당 하위 명령을 권한다.

### preflight

```sh
"$PY" "$SCRIPT" preflight
"$PY" "$SCRIPT" --terminal
```

도구 경로, `gh` 로그인, 레포 접근(VPN), 터미널(Orca · Ghostty) 연동을 점검한다. 문제마다 고칠 방법을 적는다.

### prompts

```sh
"$PY" "$SCRIPT" --prompts
```

기본 프롬프트를 `~/.pr-reviewer/prompts/defaults/` 에 꺼낸다. 바꾸고 싶은 것을 `~/.pr-reviewer/prompts/<이름>.md` 로 복사해 고치면 그 파일을 쓴다. 사용자가 무엇을 바꾸고 싶은지 말하면 그 파일을 같이 만든다. 정리 단계의 `{{FORMAT}}`(JSON 모양 지시)은 지우지 않게 한다.

### notify

```sh
"$PY" "$SCRIPT" --notify-test
```

테스트 알림을 띄운다. 알림이 보였는지 사용자에게 묻고, 안 보였으면 스크립트가 출력한 안내대로 시스템 설정의 알림 권한을 켜게 돕는다 (`open` 으로 알림 설정을 열 수 있다).

### flicker

띠를 마우스로 누르려면 Claude Code 를 `CLAUDE_CODE_NO_FLICKER=1` 로 켜야 한다. `~/.claude/settings.json` 의 `env` 와 `~/.zshrc` 에 넣는다고 말하고 동의를 받은 뒤:

```sh
"$PY" "$SCRIPT" --flicker
```

새로 켠 Claude Code 부터 적용된다고 알린다.

### uninstall

```sh
"$PY" "$SCRIPT" uninstall
```

launchd 등록을 지운다. 리뷰 기록과 worktree 는 `~/.pr-reviewer` 에 남는다고 알린다. 띠까지 지우려면 `claude plugin uninstall review-buttons@pr-action-bar` 를 쓴다(사용자가 원할 때만).
