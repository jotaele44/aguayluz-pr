import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { GitBranch, Search, GitPullRequest, GitMerge } from 'lucide-react'
import Panel from '@/components/common/Panel'
import StatTile from '@/components/common/StatTile'

export default function RepoAnalyzerPage() {
  const [repo, setRepo] = useState('jotaele44/aguayluz-pr')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const analyze = async () => {
    if (!repo.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const [owner, name] = repo.split('/')
      if (!owner || !name) throw new Error('Use format: owner/repo')

      const [prsRes, repoRes] = await Promise.all([
        fetch(`https://api.github.com/repos/${owner}/${name}/pulls?state=all&per_page=30`, {
          headers: { Accept: 'application/vnd.github.v3+json' },
        }),
        fetch(`https://api.github.com/repos/${owner}/${name}`, {
          headers: { Accept: 'application/vnd.github.v3+json' },
        }),
      ])

      if (!prsRes.ok) throw new Error(`GitHub API ${prsRes.status}: ${prsRes.statusText}`)
      const prs = await prsRes.json()
      const repoData = repoRes.ok ? await repoRes.json() : {}
      setResult({ prs, repo: repoData })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const merged = result?.prs.filter((p) => p.merged_at).length ?? 0
  const open = result?.prs.filter((p) => p.state === 'open').length ?? 0
  const closed = result?.prs.filter((p) => p.state === 'closed' && !p.merged_at).length ?? 0

  return (
    <div className="p-6 space-y-6 max-w-[1200px]">
      <div>
        <h1 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
          <GitBranch className="h-5 w-5 text-violet-400" />
          Repo Analyzer
        </h1>
        <p className="text-xs text-slate-500 mt-0.5">Analyze GitHub repository PR history and activity</p>
      </div>

      <div className="flex gap-2 max-w-lg">
        <Input
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && analyze()}
          placeholder="owner/repo"
          className="bg-slate-950 border-slate-800 text-sm"
        />
        <Button onClick={analyze} disabled={loading} className="shrink-0">
          <Search className="h-4 w-4 mr-2" />
          {loading ? 'Analyzing…' : 'Analyze'}
        </Button>
      </div>

      {error && (
        <p className="text-sm text-red-400 bg-red-950/30 border border-red-900 rounded-lg p-3">{error}</p>
      )}

      {loading && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14 w-full rounded-lg" />)}
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatTile label="Stars" value={(result.repo.stargazers_count ?? 0).toLocaleString()} />
            <StatTile label="Open Issues" value={(result.repo.open_issues_count ?? 0).toLocaleString()} />
            <StatTile label="Language" value={result.repo.language ?? '—'} />
            <StatTile label="Default Branch" value={result.repo.default_branch ?? 'main'} />
          </div>

          <div className="grid grid-cols-3 gap-4">
            <StatTile label="Merged PRs" value={merged} valueClass="text-violet-400" />
            <StatTile label="Open PRs" value={open} valueClass="text-emerald-400" />
            <StatTile label="Closed PRs" value={closed} valueClass="text-red-400" />
          </div>

          <Panel className="p-5">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
              <GitPullRequest className="h-3.5 w-3.5" />
              Recent Pull Requests ({result.prs.length} shown)
            </h3>
            <div className="space-y-2">
              {result.prs.map((pr) => (
                <a
                  key={pr.number}
                  href={pr.html_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-start gap-3 p-3 rounded-md bg-slate-800/50 border border-slate-700/50 hover:bg-slate-800 transition-colors"
                >
                  {pr.merged_at
                    ? <GitMerge className="h-3.5 w-3.5 text-violet-400 shrink-0 mt-0.5" />
                    : <GitPullRequest className={`h-3.5 w-3.5 shrink-0 mt-0.5 ${pr.state === 'open' ? 'text-emerald-400' : 'text-red-400'}`} />
                  }
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-200 truncate">{pr.title}</p>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      #{pr.number} · {pr.user?.login} · {pr.created_at?.slice(0, 10)}
                    </p>
                  </div>
                  <Badge
                    variant="outline"
                    className={`text-[10px] shrink-0 ${
                      pr.merged_at ? 'text-violet-400 border-violet-800' :
                      pr.state === 'open' ? 'text-emerald-400 border-emerald-800' :
                      'text-red-400 border-red-900'
                    }`}
                  >
                    {pr.merged_at ? 'merged' : pr.state}
                  </Badge>
                </a>
              ))}
              {result.prs.length === 0 && (
                <p className="text-sm text-slate-500 text-center py-4">No pull requests found</p>
              )}
            </div>
          </Panel>
        </div>
      )}
    </div>
  )
}
