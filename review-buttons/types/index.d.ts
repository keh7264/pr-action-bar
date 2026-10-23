/** pr-reviewer 가 status.json 의 items / prs 에 쓰는 PR 한 건. */
export type Pr = {
  repo: string
  short: string
  number: number
  url: string
  title: string
  branch: string
  /** 포크에서 온 PR. This PR 줄 매칭에서 뺀다 */
  cross_repo: boolean
  action: string
  mine: boolean
  /** 누르면 Claude 세션이 열리는지(session) 브라우저가 열리는지(url). hover 색도 이걸로 정한다 */
  opens: 'session' | 'url'
  page_url: string | null
  review_file: string | null
}

export type Status = {
  updatedAt: string | null
  items: Pr[]
  prs: Pr[]
  gitDirs: Record<string, string>
  pausedUntil: string | null
  python: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'review-buttons': {
      status: Status
      thisPr: Pr | null
      refreshing: boolean
    }
  }
}
