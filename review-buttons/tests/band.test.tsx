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

type World = { files: Record<string, string>; cwd: string; branch: string; runs: string[][] }

function world(on: On, w: World) {
  const clock = mock.clock(on)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  on('env.get', (_, e) => ({ value: e.name === 'HOME' ? HOME : undefined }))
  on('session.cwd', () => ({ value: w.cwd }))
  on('fs.exists', (_, e) => ({ value: e.path in w.files }))
  on('fs.read', (_, e) => ({ value: w.files[e.path] ?? '' }))
  on('ui.toast', () => ({ value: undefined }))
  on('process.run', (_, e) => {
    w.runs.push([...e.argv])
    const a = e.argv.join(' ')
    const out = a.includes('--git-common-dir') ? '/w/app/.git\n' : a.includes('--show-current') ? `${w.branch}\n` : ''
    return { value: { exitCode: 0, stdout: out, stderr: '' } }
  })
  return clock
}

const start = ($: any) => $.session.start({ cwd: '/w/app', surface: 'terminal', isInteractive: true })

test('띠에 내 PR · 팀 PR · This PR 이 그려진다', async ($, on) => {
  const w: World = { files: { [STATUS]: JSON.stringify(STATUS_JSON) }, cwd: '/w/app', branch: 'feature/TEST-1', runs: [] }
  world(on, w)
  await start($)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
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
  const w: World = { files: { [STATUS]: JSON.stringify(STATUS_JSON) }, cwd: '/w/app', branch: 'feature/TEST-1', runs: [] }
  world(on, w)
  await start($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
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
  const w: World = { files: { [STATUS]: JSON.stringify(STATUS_JSON) }, cwd: `${HOME}/.pr-reviewer/wt/app-8/src`, branch: '', runs: [] }
  world(on, w)
  await start($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ key: 'this-title' }))?.text).toBe('feat: x (#8)')
  await ui.unmount()
})

test('status.json 이 없으면 띠를 그리지 않는다', async ($, on) => {
  const w: World = { files: {}, cwd: '/w/app', branch: 'feature/TEST-1', runs: [] }
  world(on, w)
  await start($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /My PR/ })).toBeUndefined()
  await ui.unmount()
})

test('status.json 이 깨지면 직전 띠를 그대로 둔다', async ($, on) => {
  const w: World = { files: { [STATUS]: JSON.stringify(STATUS_JSON) }, cwd: '/w/app', branch: 'x', runs: [] }
  const clock = world(on, w)
  await start($)
  w.files[STATUS] = '{"updated_at": '
  await clock.advance(30_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ key: 'app#7' }))?.text).toBe('app#7')
  await ui.unmount()
})
