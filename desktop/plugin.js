// On-Brand: Desktop pane. Plain ES module, loaded uncompiled by Hermes Desktop (no JSX, no build).
// Talks only to this plugin's own backend (dashboard/plugin_api.py) through ctx.rest, and refreshes
// when the agent half broadcasts plugin.on-brand.* events.
import {
  Badge,
  Button,
  CopyButton,
  EmptyState,
  ScrollArea,
  SegmentedControl,
  StatusDot,
  Textarea,
  ToggleRow,
  queryClient,
  relativeTime,
  useQuery
} from '@hermes/plugin-sdk'
import { createElement as h, useState } from 'react'

const KEY = ['on-brand', 'state']
let api = null // set in register(); the plugin-scoped ctx.rest

const OUTCOME = {
  fixed: { variant: 'success', label: 'fixed' },
  passed: { variant: 'muted', label: 'on brand' },
  flagged: { variant: 'warn', label: 'needs you' },
  blocked: { variant: 'destructive', label: 'blocked' }
}

const muted = { color: 'var(--ui-text-tertiary)' }
const secondary = { color: 'var(--ui-text-secondary)' }
const line = { borderTop: '1px solid var(--ui-stroke-secondary)' }

function post(path, body) {
  return api(path, { method: 'POST', body }).then(data => {
    queryClient.setQueryData(KEY, data)
    return data
  })
}

function Section({ title, children, right }) {
  return h('div', { className: 'px-3 py-2.5', style: line },
    h('div', { className: 'mb-2 flex items-center justify-between text-[0.65rem] uppercase tracking-wide', style: muted },
      h('span', null, title), right || null),
    children)
}

function Header({ state }) {
  const active = state.active
  return h('div', { className: 'flex items-center gap-2 px-3 py-2.5' },
    h(StatusDot, { tone: active ? 'good' : 'muted' }),
    h('div', { className: 'min-w-0 flex-1' },
      h('div', { className: 'truncate text-sm font-medium' }, active ? active.display_name || active.name : 'On-Brand is off'),
      h('div', { className: 'truncate text-xs', style: muted },
        active
          ? [active.person === 'third' ? 'third person' : active.person === 'first' ? 'speaks as "we"' : 'any person',
             ...(active.packs || []).map(p => p + ' compliance')].join(' · ')
          : 'Pick a brand to start enforcing its rules')))
}

function Brands({ state }) {
  const current = state.active && state.active.name
  if (!state.profiles.length) {
    return h('div', { className: 'text-xs', style: secondary }, 'No brands yet. Type /onbrand starter or ask Hermes to set one up.')
  }
  return h('div', { className: 'flex flex-wrap gap-1' },
    state.profiles.map(p => h(Button, {
      key: p.name,
      size: 'xs',
      variant: p.name === current ? 'default' : 'chip',
      onClick: () => post('/use', { name: p.name })
    }, p.label)),
    h(Button, { key: '__off', size: 'xs', variant: current ? 'ghost' : 'chip', onClick: () => post('/use', { name: null }) }, 'Off'))
}

function Controls({ state }) {
  const s = state.settings
  return h('div', { className: 'flex flex-col gap-1' },
    h(ToggleRow, {
      label: 'Auto-fix drafts',
      description: 'Rewrite off-brand copy until it passes',
      checked: !!s.auto_fix,
      onChange: v => post('/settings', { auto_fix: !!v })
    }),
    h(ToggleRow, {
      label: 'Outbound gate',
      description: 'Block off-brand posts before they send',
      checked: !!s.gate,
      onChange: v => post('/settings', { gate: !!v })
    }),
    h('div', { className: 'flex items-center justify-between pt-1 text-xs', style: secondary },
      h('span', null, 'Check'),
      h(SegmentedControl, {
        options: [{ id: 'drafts', label: 'Copy blocks' }, { id: 'all', label: 'Whole reply' }],
        value: s.scope || 'drafts',
        onChange: id => post('/settings', { scope: id })
      })))
}

function Stats({ stats }) {
  const cell = (n, label) => h('div', { className: 'flex-1 text-center' },
    h('div', { className: 'text-base font-medium tabular-nums' }, n),
    h('div', { className: 'text-[0.65rem]', style: muted }, label))
  return h('div', { className: 'flex' },
    cell(stats.checked, 'checked'), cell(stats.fixed, 'fixed'), cell(stats.blocked, 'blocked'), cell(stats.passed, 'clean'))
}

function Score({ before, after }) {
  if (before == null || before === after) return h('span', { className: 'tabular-nums text-xs', style: secondary }, after)
  return h('span', { className: 'tabular-nums text-xs', style: secondary }, `${before} → ${after}`)
}

function Entry({ item }) {
  const look = OUTCOME[item.outcome] || OUTCOME.passed
  const [open, setOpen] = useState(item.outcome !== 'passed')
  const where = item.kind === 'gate' ? `post via ${item.tool}` : 'draft'
  const fixed = item.fixed || []
  const remaining = item.remaining || []
  return h('div', { className: 'px-3 py-2', style: line },
    h('button', { type: 'button', className: 'flex w-full items-center gap-2 text-left', onClick: () => setOpen(!open) },
      h(Badge, { variant: look.variant, size: 'xs' }, look.label),
      h('span', { className: 'min-w-0 flex-1 truncate text-xs' }, `${item.brand_label || item.brand} · ${where}`),
      h(Score, { before: item.score_before, after: item.score_after }),
      h('span', { className: 'text-[0.65rem]', style: muted }, item.ts ? relativeTime(item.ts * 1000) : '')),
    open && h('div', { className: 'mt-1.5 flex flex-col gap-1 text-xs' },
      fixed.map((f, i) => h('div', { key: 'f' + i, style: secondary }, '✓ ' + f)),
      remaining.map((r, i) => h('div', { key: 'r' + i, style: { color: 'var(--ui-text-primary)' } }, '• ' + r)),
      item.after && h('div', { className: 'mt-1 flex items-start gap-1.5' },
        h('div', { className: 'min-w-0 flex-1 whitespace-pre-wrap rounded-[4px] px-2 py-1.5',
          style: { background: 'var(--ui-bg-tertiary)', ...secondary } }, item.after),
        item.outcome !== 'blocked' && h(CopyButton, { text: item.after, appearance: 'icon' }))))
}

function QuickCheck({ enabled }) {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = () => {
    if (!text.trim()) return
    setBusy(true)
    api('/check', { method: 'POST', body: { text } })
      .then(setResult, err => setResult({ error: String((err && err.message) || err) }))
      .finally(() => setBusy(false))
  }
  return h('div', { className: 'flex flex-col gap-1.5' },
    h(Textarea, { value: text, rows: 3, placeholder: 'Paste copy to score it', onChange: e => setText(e.target.value) }),
    h('div', { className: 'flex items-center gap-2' },
      h(Button, { size: 'xs', variant: 'outline', disabled: !enabled || busy || !text.trim(), onClick: run }, busy ? 'Checking…' : 'Check'),
      !enabled && h('span', { className: 'text-xs', style: muted }, 'Pick a brand first')),
    result && (result.error
      ? h('div', { className: 'text-xs', style: secondary }, result.error)
      : h('div', { className: 'flex flex-col gap-0.5 text-xs' },
          h('div', { className: 'flex items-center gap-2' },
            h(Badge, { size: 'xs', variant: result.passed ? 'success' : 'destructive' }, result.passed ? 'passes' : 'fails'),
            h('span', { className: 'tabular-nums', style: secondary }, `${result.score}/100`)),
          (result.violations || []).map((v, i) => h('div', { key: i, style: secondary }, '• ' + v.detail)))))
}

function Pane() {
  const { data, isLoading, isError } = useQuery({ queryKey: KEY, queryFn: () => api('/state'), refetchInterval: 15000 })
  if (isLoading) return h(EmptyState, { title: 'Loading On-Brand…' })
  if (isError || !data) {
    return h(EmptyState, { title: 'On-Brand backend is off', description: 'Enable the on-brand plugin in Hermes (hermes plugins enable on-brand), then restart the gateway.' })
  }
  return h(ScrollArea, { className: 'h-full' },
    h('div', { className: 'flex flex-col pb-3' },
      h(Header, { state: data }),
      h(Section, { title: 'Brand' }, h(Brands, { state: data })),
      h(Section, { title: 'Enforcement' }, h(Controls, { state: data })),
      h(Section, { title: 'Totals' }, h(Stats, { stats: data.stats })),
      h(Section, { title: 'Quick check' }, h(QuickCheck, { enabled: !!data.active })),
      h(Section, { title: 'Live feed' },
        data.history.length
          ? h('div', { style: { margin: '0 -0.75rem' } }, data.history.map((item, i) => h(Entry, { key: `${item.ts}-${i}`, item })))
          : h('div', { className: 'text-xs', style: secondary }, 'Nothing checked yet. Ask Hermes to write something for the active brand.'))))
}

function StatusChip() {
  const { data } = useQuery({ queryKey: KEY, queryFn: () => api('/state'), refetchInterval: 15000 })
  const active = data && data.active
  return h('span', { className: 'flex items-center gap-1 px-1 text-xs', style: secondary },
    h(StatusDot, { tone: active ? 'good' : 'muted' }),
    active ? `On-Brand: ${active.display_name || active.name}` : 'On-Brand off')
}

export default {
  id: 'on-brand',
  name: 'On-Brand',
  register(ctx) {
    api = ctx.rest
    const refresh = () => queryClient.invalidateQueries({ queryKey: KEY })
    for (const evt of ['checked', 'gate', 'profiles']) ctx.onEvent(`plugin.on-brand.${evt}`, refresh)
    ctx.onDispose(() => { api = null })
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'On-Brand',
      data: { placement: 'right', width: '320px' },
      render: () => h(Pane, null)
    })
    ctx.register({ id: 'status', area: 'statusBar.right', render: () => h(StatusChip, null) })
  }
}
