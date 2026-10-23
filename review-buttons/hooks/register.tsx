import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Pr, Status } from '../types'

const EMPTY: Status = { updatedAt: null, items: [], prs: [], gitDirs: {}, pausedUntil: null, python: null }

const status = atom({ plugin: 'review-buttons', key: 'status' } as const, EMPTY)
const thisPr = atom({ plugin: 'review-buttons', key: 'thisPr' } as const, null)
const refreshing = atom({ plugin: 'review-buttons', key: 'refreshing' } as const, false)

const CLICK_TIMEOUT_MS = 20_000

// 색은 괄호와 상태 이름에만 넣는다. 테마 키라서 라이트 테마에서는 다른 값으로 바뀐다
const ACTION_COLORS: Record<string, string> = {
  'Resolve conflicts': 'error',
  'Fix CI': 'error',
  'Address changes': 'error',
  Reply: 'warning',
  'Re-review': 'warning',
  'Check merge': 'warning',
  'Needs review': 'suggestion',
  Updated: 'planMode',
  Reviewing: 'ide',
  Merge: 'success',
}
const colorOf = (action: string) => ACTION_COLORS[action] ?? 'inactive'

// 라벨과 링크 색은 테마 키에 없어서 hex 를 직접 넣는다
const GROUPS = [
  { key: 'mine', label: 'My PR', color: '#3EB489', mine: true },
  { key: 'team', label: 'Team PR', color: '#5BB8F5', mine: false },
] as const
const THIS_PR_COLOR = '#A66CFF'
const JIRA_COLOR = '#4C9AFF'
const ISSUE_KEY = /[A-Z][A-Z0-9]+-\d+/

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

async function home($: EngineInterface) {
  return (await $.env.get('HOME')) ?? ''
}

async function loadStatus($: EngineInterface) {
  const path = `${await home($)}/.pr-reviewer/status.json`
  if (!(await $.fs.exists(path))) {
    // 제거한 뒤에는 옛 PR 목록과 버튼이 남지 않게 비운다
    await update($, status, prev => (same(prev, EMPTY) ? prev : EMPTY))
    return
  }
  let raw: any
  try {
    raw = JSON.parse(await $.fs.read(path))
  } catch {
    return // 읽기 실패(쓰는 중 등)면 직전 값을 그대로 둔다
  }
  const next: Status = {
    updatedAt: raw.updated_at ?? null,
    items: raw.items ?? [],
    prs: raw.prs ?? [],
    gitDirs: raw.git_dirs ?? {},
    pausedUntil: raw.paused_until ?? null,
    python: raw.python ?? null,
  }
  // 값이 바뀌었을 때만 써서 30초마다 다시 그리지 않는다
  await update($, status, prev => (same(prev, next) ? prev : next))
}

async function findThisPr($: EngineInterface): Promise<Pr | null> {
  const { prs, gitDirs } = await read($, status)
  const cwd = await $.session.cwd()
  const reviewTree = /\/\.pr-reviewer\/wt\/([^/]+)-(\d+)(?:\/|$)/.exec(cwd)
  if (reviewTree) {
    return prs.find(p => p.repo === reviewTree[1] && p.number === Number(reviewTree[2])) ?? null
  }
  try {
    const [gitDir, branch] = await Promise.all([
      $.process.run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir'], { timeoutMs: 5000 }),
      $.process.run(['git', '-C', cwd, 'branch', '--show-current'], { timeoutMs: 5000 }),
    ])
    if (gitDir.exitCode !== 0 || branch.exitCode !== 0) return null
    const repo = Object.entries(gitDirs).find(([, dir]) => dir === gitDir.stdout.trim())?.[0]
    // 포크에서 온 PR 은 브랜치 이름이 같아도 내 브랜치가 아니다
    return prs.find(p => p.repo === repo && !p.cross_repo && p.branch === branch.stdout.trim()) ?? null
  } catch {
    return null
  }
}

async function tick($: EngineInterface) {
  await loadStatus($)
  const pr = await findThisPr($)
  await update($, thisPr, prev => (same(prev, pr) ? prev : pr))
}

async function runScript($: EngineInterface, args: string[]) {
  const script = `${await home($)}/.pr-reviewer/bin/pr-reviewer.py`
  try {
    // launchd 와 같은 python 을 쓴다 (install 이 status.json 에 적어 둔다)
    const python = (await read($, status)).python ?? '/usr/bin/python3'
    const { exitCode, stderr } = await $.process.run([python, script, ...args], { timeoutMs: CLICK_TIMEOUT_MS })
    if (exitCode !== 0) {
      const last = stderr.trim().split('\n').pop() || `종료 코드 ${exitCode}`
      $.ui.toast(`pr-reviewer: ${last}`)
    }
  } catch {
    $.ui.toast('pr-reviewer: 응답이 없어 중단했다')
  }
}

async function openUrl($: EngineInterface, url: string) {
  try {
    await $.process.run(['/usr/bin/open', url], { timeoutMs: 5000 })
  } catch {
    $.ui.toast(`열지 못했다: ${url}`)
  }
}

async function openPr($: EngineInterface, pr: Pr) {
  // page_url 이 있으면 바로 열고, 없으면 봇 스크립트가 세션 탭을 찾는다 (어느 상태를 PR 페이지로 열지는 봇 한 곳에서 정한다)
  if (pr.page_url) return openUrl($, pr.page_url)
  return runScript($, ['--open', pr.repo, String(pr.number), ...(pr.mine ? ['--mine'] : [])])
}

async function refresh($: EngineInterface) {
  if (await read($, refreshing)) return
  await update($, refreshing, () => true)
  try {
    await runScript($, ['--refresh', '--full'])
    await tick($)
  } finally {
    await update($, refreshing, () => false)
  }
}

function groupByAction(items: Pr[]): [string, Pr[]][] {
  const groups = new Map<string, Pr[]>()
  for (const t of items) groups.set(t.action, [...(groups.get(t.action) ?? []), t])
  return [...groups.entries()]
}

function hhmm(iso: string | null) {
  const m = iso ? /T(\d{2}:\d{2})/.exec(iso) : null
  return m ? m[1] : '--:--'
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // 헤드리스(claude -p) 세션에서는 아무것도 하지 않는다. 리뷰 봇이 띄운 리뷰마다 띠 로직이 돌지 않게
    if (e.isInteractive) {
      await tick($)
      $.clock.every(30_000, () => void tick($))
    }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)

    const { Box, Button, Text } = $.ui.resolve(e)
    const { items, updatedAt, pausedUntil } = await read($, status)
    const current = await read($, thisPr)
    const busy = await read($, refreshing)
    // 같은 자리를 쓰는 다른 mod 가 그린 것도 끝에 붙인다
    const below = await next(e)

    if (!updatedAt && items.length === 0) return below

    const clickable = e.viewport?.isFullscreen !== false
    const issue = current ? ISSUE_KEY.exec(current.branch)?.[0] ?? ISSUE_KEY.exec(current.title)?.[0] : undefined
    const hoverFor = (opens: string) => ({ underline: true, bold: true, color: opens === 'session' ? 'claude' : 'text' })

    return (
      <Box flexDirection="column">
        <Box key="meta" columnGap={2}>
          <Box key="frame-refresh">
            <Button
              key="refresh"
              label={busy ? '↻ 가져오는 중' : `↻ ${hhmm(updatedAt)}`}
              plain
              hover={{ underline: true }}
              onPress={() => void refresh($)}
            />
          </Box>
          {pausedUntil ? <Text color="warning">{`리뷰 쉬는 중 (${hhmm(pausedUntil)}까지)`}</Text> : null}
          {clickable ? null : <Text dimColor>클릭하려면 CLAUDE_CODE_NO_FLICKER=1 로 실행</Text>}
        </Box>
        {GROUPS.map(g => {
          const byAction = groupByAction(items.filter(t => t.mine === g.mine))
          return byAction.length > 0 ? (
            <Box key={`group-${g.key}`}>
              <Box width={11} flexShrink={0}>
                <Text color={g.color} bold>{`* ${g.label}`}</Text>
              </Box>
              <Box columnGap={2} flexWrap="wrap" flexShrink={1}>
                {byAction.map(([action, prs]) => (
                  <Box key={`action-${g.key}-${action}`} columnGap={1}>
                    <Text color={colorOf(action)} bold>[</Text>
                    <Text color={colorOf(action)} bold>{action}</Text>
                    {prs.map(t => (
                      // hover 를 쓰는 Button 은 key 가 있는 Box 로 감싼다. 아니면 트리 검증에 실패해 띠가 통째로 사라진다
                      <Box key={`frame-${t.repo}#${t.number}`}>
                        <Button
                          key={`${t.repo}#${t.number}`}
                          label={`${t.short}#${t.number}`}
                          plain
                          hover={hoverFor(t.opens)}
                          onPress={() => void openPr($, t)}
                        />
                      </Box>
                    ))}
                    <Text color={colorOf(action)} bold>]</Text>
                  </Box>
                ))}
              </Box>
            </Box>
          ) : null
        })}
        {current ? (
          <Box key="this-pr" columnGap={2}>
            <Box width={9} flexShrink={0}>
              <Text color={THIS_PR_COLOR} bold>* This PR</Text>
            </Box>
            <Box key="frame-this-action">
              <Button
                key="this-action"
                label={`[ ${current.action} ]`}
                plain
                hover={{ underline: true }}
                onPress={() => void openUrl($, current.page_url ?? current.url)}
              />
            </Box>
            <Box key="frame-this-title" flexShrink={1}>
              <Button
                key="this-title"
                label={`${current.title} (#${current.number})`}
                plain
                hover={{ underline: true }}
                onPress={() => void openUrl($, current.url)}
              />
            </Box>
            {issue ? (
              <Box key="frame-this-issue">
                <Button
                  key="this-issue"
                  label={`[ ${issue} ]`}
                  plain
                  hover={{ underline: true, color: JIRA_COLOR }}
                  onPress={() => void runScript($, ['--open-issue', issue])}
                />
              </Box>
            ) : null}
            {current.review_file ? (
              <Box key="frame-this-review">
                <Button
                  key="this-review"
                  label="리뷰 파일"
                  plain
                  hover={{ underline: true }}
                  onPress={() => void openUrl($, `file://${current.review_file}`)}
                />
              </Box>
            ) : null}
          </Box>
        ) : null}
        {below}
      </Box>
    )
  })
}
