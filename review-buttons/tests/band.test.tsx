import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const HOME = '/Users/me'
const STATUS = `${HOME}/.pr-reviewer/status.json`

const pr = (over: Record<string, unknown>) => ({
  repo: 'app', short: 'app', number: 1, url: 'https://github.com/o/app/pull/1', title: 'feat: x',
  branch: 'feature/x', cross_repo: false, action: 'Needs review', mine: false, opens: 'url',
  page_url: 'https://github.com/o/app/pull/1', review_file: null, issue_key: null, issue_url: null,
  ...over,
})

const mine = pr({ number: 7, title: 'TEST-1 median', branch: 'feature/TEST-1', action: 'Awaiting approval', mine: true,
  url: 'https://github.com/o/app/pull/7', page_url: 'https://github.com/o/app/pull/7',
  issue_key: 'TEST-1', issue_url: 'https://jira/TEST-1', review_file: `${HOME}/.pr-reviewer/reviews/app/7-abc.md` })
const team = pr({ number: 8, action: 'Needs review', opens: 'session', page_url: null })

const STATUS_JSON = {
  updated_at: '2026-10-24T15:31:34+09:00', python: '/opt/homebrew/bin/python3',
  items: [mine, team], prs: [mine, team], git_dirs: { app: '/w/app/.git' }, paused_until: null,
}

const BAND = {
  plugin: 'review-buttons',
  component: 'AbovePrompt',
  requestId: 'above-prompt',
  viewport: { columns: 125, rows: 40, isFullscreen: true },
  props: { hasSurvey: false, isWorking: false, maxRows: 20, bodyColumns: 120, scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

type World = {
  files: Record<string, string>; cwd: string; branch: string; runs: string[][]
  env?: Record<string, string>; gitDir?: string; hold?: Promise<void>
  /** 플러그인 안에 든 봇 스크립트 본문 */
  bundled?: string
}

function world(on: On, w: World) {
  const clock = mock.clock(on)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  on('env.get', (_, e) => ({ value: e.name === 'HOME' ? HOME : w.env?.[e.name] }))
  on('session.cwd', () => ({ value: w.cwd }))
  on('fs.exists', (_, e) => ({ value: e.path in w.files }))
  on('fs.read', (_, e) => ({
    value: e.path.endsWith('/pr-reviewer/pr-reviewer.py') ? (w.bundled ?? '') : (w.files[e.path] ?? ''),
  }))
  on('ui.toast', () => ({ value: undefined }))
  on('process.run', async (_, e) => {
    w.runs.push([...e.argv])
    const a = e.argv.join(' ')
    if (a.includes('--refresh') && w.hold) await w.hold
    const out = a.includes('--git-common-dir') ? `${w.gitDir ?? '/w/app/.git'}\n` : a.includes('--show-current') ? `${w.branch}\n` : ''
    return { value: { exitCode: 0, stdout: out, stderr: '' } }
  })
  return clock
}

async function setup($: any, on: On, over: Partial<World> = {}) {
  const w: World = { files: { [STATUS]: JSON.stringify(STATUS_JSON) }, cwd: '/w/app', branch: 'feature/TEST-1', runs: [], ...over }
  const clock = world(on, w)
  await $.session.start({ cwd: '/w/app', surface: 'terminal', isInteractive: true })
  return { w, clock }
}

const mount = ($: any, surface: 'terminal' | 'desktop' = 'terminal') => $.ui.mount({ ...BAND, surface })

test('띠에 내 PR · 팀 PR · This PR 이 그려진다', async ($, on) => {
  await setup($, on)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await mount($, surface)
    expect(await ui.find({ type: 'Text', text: /My PR/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Team PR/ })).toBeDefined()
    expect((await ui.find({ key: 'app#7' }))?.text).toBe('app#7')
    expect((await ui.find({ key: 'app#8' }))?.text).toBe('app#8')
    expect((await ui.find({ key: 'this-title' }))?.text).toBe('TEST-1 median (#7)')
    expect((await ui.find({ key: 'this-issue' }))?.text).toBe('[ TEST-1 ]')
    expect(await ui.find({ key: 'this-review' })).toBeDefined()
    await ui.unmount()
  }
})

test('누르면 PR 페이지 · 봇 스크립트 · 리뷰 파일이 열린다', async ($, on) => {
  const { w } = await setup($, on)
  const ui = await mount($)
  w.runs.length = 0
  await ui.press({ key: 'app#7' })
  expect(w.runs.at(-1)).toEqual(['/usr/bin/open', 'https://github.com/o/app/pull/7'])
  await ui.press({ key: 'app#8' })
  expect(w.runs.at(-1)).toEqual(['/opt/homebrew/bin/python3', `${HOME}/.pr-reviewer/bin/pr-reviewer.py`, '--open', 'app', '8'])
  await ui.press({ key: 'this-review' })
  expect(w.runs.at(-1)?.[0]).toBe('/usr/bin/open')
  expect(w.runs.at(-1)?.[1]).toContain('7-abc.md')
  await ui.unmount()
})

test('리뷰 worktree 에서는 그 PR 이 This PR 이다', async ($, on) => {
  await setup($, on, { cwd: `${HOME}/.pr-reviewer/wt/app-8/src`, branch: '' })
  const ui = await mount($)
  expect((await ui.find({ key: 'this-title' }))?.text).toBe('feat: x (#8)')
  await ui.unmount()
})

test('status.json 이 없으면 띠를 그리지 않는다', async ($, on) => {
  await setup($, on, { files: {} })
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /My PR/ })).toBeUndefined()
  await ui.unmount()
})

test('status.json 이 깨지면 직전 띠를 그대로 둔다', async ($, on) => {
  const { w, clock } = await setup($, on, { branch: 'x' })
  w.files[STATUS] = '{"updated_at": '
  await clock.advance(30_000)
  const ui = await mount($)
  expect((await ui.find({ key: 'app#7' }))?.text).toBe('app#7')
  await ui.unmount()
})

test('PR_REVIEWER_HOME 을 따른다: status.json · 리뷰 worktree · 스크립트 경로', async ($, on) => {
  const base = '/opt/prr'
  const json = { ...STATUS_JSON, ui: { script: `${base}/bin/pr-reviewer.py`, worktrees: `${base}/wt` } }
  const { w } = await setup($, on, {
    files: { [`${base}/status.json`]: JSON.stringify(json) }, env: { PR_REVIEWER_HOME: `${base}/` },
    cwd: `${base}/wt/app-8`, branch: '',
  })
  const ui = await mount($)
  expect((await ui.find({ key: 'this-title' }))?.text).toBe('feat: x (#8)')
  w.runs.length = 0
  await ui.press({ key: 'app#8' })
  expect(w.runs.at(-1)?.[1]).toBe(`${base}/bin/pr-reviewer.py`)
  await ui.unmount()
})

test('조회에 실패한 레포는 경고를 띄운다', async ($, on) => {
  await setup($, on, { files: { [STATUS]: JSON.stringify({ ...STATUS_JSON, failed_repos: ['app'] }) } })
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /조회 실패: app/ })).toBeDefined()
  expect((await ui.find({ key: 'app#7' }))?.text).toBe('app#7')
  await ui.unmount()
})

test('조회 실패 경고에 남겨 둔 줄의 조회 시각을 적는다', async ($, on) => {
  const status = { ...STATUS_JSON, failed_repos: ['app'], checked_at: { app: '2026-01-01T05:20:00Z' } }
  await setup($, on, { files: { [STATUS]: JSON.stringify(status) } })
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /조회 실패: app \(1\/1 \d\d:\d\d 기준\)/ })).toBeDefined()
  await ui.unmount()
})

test('오늘 조회한 값이면 시각만 적는다', async ($, on) => {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const today = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T09:30:00+09:00`
  const status = { ...STATUS_JSON, failed_repos: ['app'], checked_at: { app: today } }
  await setup($, on, { files: { [STATUS]: JSON.stringify(status) } })
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /조회 실패: app \(09:30 기준\)/ })).toBeDefined()
  await ui.unmount()
})

test('↻ 를 빠르게 두 번 눌러도 새로고침은 한 번만 돈다', async ($, on) => {
  let release = () => {}
  const hold = new Promise<void>(r => { release = r })
  const { w } = await setup($, on, { hold })
  const ui = await mount($)
  await Promise.all([ui.press({ key: 'refresh' }), ui.press({ key: 'refresh' })])
  release()
  await hold
  expect(w.runs.filter(r => r.includes('--refresh'))).toHaveLength(1)
  await ui.unmount()
})

test('리뷰 대상이 아닌 레포에서는 브랜치를 묻지 않고 git-common-dir 도 한 번만 묻는다', async ($, on) => {
  const { w, clock } = await setup($, on, { gitDir: '/elsewhere/.git' })
  await clock.advance(30_000)
  await clock.advance(30_000)
  expect(w.runs.filter(r => r.includes('--show-current'))).toHaveLength(0)
  expect(w.runs.filter(r => r.includes('--git-common-dir'))).toHaveLength(1)
})

test('같은 브랜치에 PR 이 여럿이면 할 일이 급한 것을 This PR 로 고른다', async ($, on) => {
  const other = { ...mine, number: 9, title: 'release to main', action: 'Awaiting approval' }
  const urgent = { ...mine, number: 10, title: 'release to develop', action: 'Fix CI' }
  const json = { ...STATUS_JSON, prs: [other, urgent, team], items: [other, urgent, team] }
  await setup($, on, { files: { [STATUS]: JSON.stringify(json) } })
  const ui = await mount($)
  expect((await ui.find({ key: 'this-action' }))?.text).toBe('[ Fix CI ]')
  await ui.unmount()
})

test('설치된 봇 스크립트가 플러그인 안의 것과 버전이 다르면 알린다', async ($, on) => {
  await setup($, on, {
    files: { [STATUS]: JSON.stringify({ ...STATUS_JSON, version: '0.1.0' }) },
    bundled: '#!/usr/bin/env python3\nVERSION = "0.2.0"\n',
  })
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /봇 스크립트 0\.1\.0 → 0\.2\.0 업데이트 필요/ })).toBeDefined()
  await ui.unmount()
})

test('옛 status.json(버전 없음)도 업데이트를 알리고, 같으면 조용하다', async ($, on) => {
  const { w, clock } = await setup($, on, { bundled: 'VERSION = "0.2.0"\n' })
  let ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /옛 버전 → 0\.2\.0/ })).toBeDefined()
  await ui.unmount()
  w.files[STATUS] = JSON.stringify({ ...STATUS_JSON, version: '0.2.0' })
  await clock.advance(30_000)
  ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /업데이트 필요/ })).toBeUndefined()
  await ui.unmount()
})
