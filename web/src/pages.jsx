import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react'
import {
  ArrowRight,
  Building2,
  ChartNoAxesCombined,
  ChevronDown,
  ChevronRight,
  Database,
  Factory,
  FileCheck2,
  FileText,
  Files,
  FolderArchive,
  Globe2,
  Layers3,
  Plus,
  RefreshCw,
  Search,
  Shapes,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'
import { del, get, post } from './api'
import { EmptyState, LoadingState } from './components'

const DOMAIN_LABELS = { company: '个股', industry: '行业', market: '市场', macro: '宏观', other: '其他' }
const KIND_LABELS = { temporary_source: '原始文件', source_markdown: '归档文本', report: '正式报告', output_markdown: '输出分析' }
const LIBRARY_MODES = [
  { id: 'reports', label: '正式报告', description: '从 report/ 读取研究结论与决策备忘', icon: FileCheck2 },
  { id: 'archives', label: '归档资料', description: '经 Agent 甄别整理的可复用文本', icon: FolderArchive },
  { id: 'originals', label: '原始资料', description: 'PDF、披露附件与待复核文件', icon: Files },
]
const DOMAIN_META = {
  company: { icon: Building2, label: '个股' },
  industry: { icon: Factory, label: '行业' },
  market: { icon: ChartNoAxesCombined, label: '市场' },
  macro: { icon: Globe2, label: '宏观' },
  other: { icon: Shapes, label: '其他' },
}
const moneyFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 })

function formatDate(value) {
  if (!value) return '暂无'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function shortDate(value) {
  return value ? String(value).slice(0, 10) : '暂无'
}

function formatSize(bytes) {
  if (typeof bytes !== 'number') return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function recordGroup(record) {
  if (record.storage === 'report') return 'reports'
  if (record.kind === 'temporary_source') return 'originals'
  if (record.kind === 'source_markdown') return 'archives'
  return 'reports'
}

function toNumber(value) {
  if (value === '' || value === null || value === undefined) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function calculateHoldingPnl(holding) {
  const quantity = toNumber(holding.quantity)
  const averageCost = toNumber(holding.average_cost)
  const latestPrice = toNumber(holding.latest_price)
  if (quantity === null || averageCost === null || latestPrice === null) return null
  return (latestPrice - averageCost) * quantity
}

function formatMoney(value) {
  if (toNumber(value) === null) return '—'
  return `${value >= 0 ? '+' : ''}${moneyFormatter.format(value)}`
}

function buildLibraryTree(records) {
  const domains = new Map()
  records.forEach((record) => {
    const domain = record.domain || 'other'
    const subject = record.subject || '未分类'
    const recordCategory = record.category || '未分类'
    const date = record.date || '未知日期'
    if (!domains.has(domain)) domains.set(domain, new Map())
    const subjects = domains.get(domain)
    if (!subjects.has(subject)) subjects.set(subject, new Map())
    const categories = subjects.get(subject)
    if (!categories.has(recordCategory)) categories.set(recordCategory, new Map())
    const dates = categories.get(recordCategory)
    dates.set(date, (dates.get(date) || 0) + 1)
  })
  return [...domains.entries()]
    .map(([domain, subjects]) => ({
      domain,
      count: [...subjects.values()].reduce((total, categories) => total + [...categories.values()].reduce((categoryTotal, dates) => categoryTotal + [...dates.values()].reduce((sum, count) => sum + count, 0), 0), 0),
      subjects: [...subjects.entries()]
        .map(([subject, categories]) => ({
          subject,
          count: [...categories.values()].reduce((total, dates) => total + [...dates.values()].reduce((sum, count) => sum + count, 0), 0),
          categories: [...categories.entries()]
            .map(([category, dates]) => ({
              category,
              count: [...dates.values()].reduce((total, count) => total + count, 0),
              dates: [...dates.entries()].map(([date, count]) => ({ date, count })).sort((first, second) => second.date.localeCompare(first.date)),
            }))
            .sort((first, second) => first.category.localeCompare(second.category, 'zh-CN')),
        }))
        .sort((first, second) => first.subject.localeCompare(second.subject, 'zh-CN')),
    }))
    .sort((first, second) => first.domain.localeCompare(second.domain))
}

function scopeLabel(scope) {
  const parts = [
    scope.domain && (DOMAIN_META[scope.domain]?.label || DOMAIN_LABELS[scope.domain] || scope.domain),
    scope.subject,
    scope.category,
    scope.date,
  ].filter(Boolean)
  return parts.length ? parts.join(' / ') : '全部领域'
}

function treeKey(...parts) {
  return parts.join('::')
}

function LibraryTree({ category, records, allRecords, scope, onCategoryChange, onScopeChange }) {
  const hierarchy = useMemo(() => buildLibraryTree(records), [records])
  const modeCounts = useMemo(() => allRecords.reduce((counts, record) => {
    const group = recordGroup(record)
    return { ...counts, [group]: counts[group] + 1 }
  }, { reports: 0, archives: 0, originals: 0 }), [allRecords])
  const [expandedDomains, setExpandedDomains] = useState(() => new Set())
  const [expandedSubjects, setExpandedSubjects] = useState(() => new Set())
  const [expandedCategories, setExpandedCategories] = useState(() => new Set())

  useEffect(() => {
    setExpandedDomains(new Set())
    setExpandedSubjects(new Set())
    setExpandedCategories(new Set())
  }, [category])

  const toggleExpanded = (setter, key) => {
    setter((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const clearScope = () => {
    setExpandedDomains(new Set())
    setExpandedSubjects(new Set())
    setExpandedCategories(new Set())
    onScopeChange({ domain: '', subject: '', category: '', date: '' })
  }

  return (
    <aside className="library-tree">
      <div className="tree-heading"><span>资料栏目</span><h2>先确定资料层级</h2><p>再按领域、主题和日期逐层收窄。</p></div>
      <div className="library-mode-list" aria-label="资料类别">
        {LIBRARY_MODES.map(({ id, label, description, icon: Icon }) => (
          <button type="button" className={`library-mode ${category === id ? 'active' : ''}`} aria-pressed={category === id} key={id} onClick={() => onCategoryChange(id)}>
            <span className="library-mode-icon"><Icon size={16} strokeWidth={1.8} /></span>
            <span className="library-mode-copy"><strong>{label}</strong><small>{description}</small></span>
            <b>{modeCounts[id]}</b>
          </button>
        ))}
      </div>
      <div className="tree-divider"><span>按研究范围</span></div>
      <button type="button" className={`tree-reset ${!scope.domain ? 'active' : ''}`} onClick={clearScope}><Layers3 size={14} /> <span>全部领域</span><small>{records.length}</small></button>
      <div className="tree-groups">
        {hierarchy.map(({ domain, count, subjects }) => (
          <LibraryDomain
            domain={domain}
            count={count}
            subjects={subjects}
            scope={scope}
            expandedDomains={expandedDomains}
            expandedSubjects={expandedSubjects}
            expandedCategories={expandedCategories}
            onDomainSelect={() => {
              toggleExpanded(setExpandedDomains, domain)
              onScopeChange({ domain, subject: '', category: '', date: '' })
            }}
            onSubjectSelect={(subject) => {
              toggleExpanded(setExpandedSubjects, treeKey(domain, subject))
              onScopeChange({ domain, subject, category: '', date: '' })
            }}
            onCategorySelect={(subject, itemCategory) => {
              toggleExpanded(setExpandedCategories, treeKey(domain, subject, itemCategory))
              onScopeChange({ domain, subject, category: itemCategory, date: '' })
            }}
            onDateSelect={(subject, itemCategory, date) => onScopeChange({ domain, subject, category: itemCategory, date })}
            key={domain}
          />
        ))}
      </div>
    </aside>
  )
}

function LibraryDomain({
  domain,
  count,
  subjects,
  scope,
  expandedDomains,
  expandedSubjects,
  expandedCategories,
  onDomainSelect,
  onSubjectSelect,
  onCategorySelect,
  onDateSelect,
}) {
  const domainOpen = expandedDomains.has(domain)
  const DomainIcon = DOMAIN_META[domain]?.icon || Shapes
  const domainLabel = DOMAIN_META[domain]?.label || DOMAIN_LABELS[domain] || domain
  return (
    <section className="tree-domain">
      <button type="button" className={scope.domain === domain && !scope.subject ? 'active' : ''} aria-expanded={domainOpen} onClick={onDomainSelect}>
        <span className="tree-domain-label"><span className="tree-domain-icon"><DomainIcon size={15} strokeWidth={1.8} /></span>{domainLabel}</span><span className="tree-button-meta"><small>{count}</small>{domainOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
      </button>
      {domainOpen && <div className="tree-subjects">
        {subjects.map(({ subject, count: subjectCount, categories }) => {
          const subjectKey = treeKey(domain, subject)
          const subjectOpen = expandedSubjects.has(subjectKey)
          return (
            <div className="tree-subject" key={subjectKey}>
              <button type="button" className={scope.domain === domain && scope.subject === subject && !scope.category ? 'active' : ''} aria-expanded={subjectOpen} onClick={() => onSubjectSelect(subject)}>
                <span>{subject}</span><span className="tree-button-meta"><small>{subjectCount}</small>{subjectOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
              </button>
              {subjectOpen && <div className="tree-categories">
                {categories.map(({ category: itemCategory, count: categoryCount, dates }) => {
                  const categoryKey = treeKey(domain, subject, itemCategory)
                  const categoryOpen = expandedCategories.has(categoryKey)
                  return (
                    <div className="tree-category" key={categoryKey}>
                      <button type="button" className={scope.domain === domain && scope.subject === subject && scope.category === itemCategory && !scope.date ? 'active' : ''} aria-expanded={categoryOpen} onClick={() => onCategorySelect(subject, itemCategory)}>
                        <span>{itemCategory}</span><span className="tree-button-meta"><small>{categoryCount}</small>{categoryOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
                      </button>
                      {categoryOpen && <div className="tree-dates">
                        {dates.map(({ date, count: dateCount }) => <button type="button" className={scope.domain === domain && scope.subject === subject && scope.category === itemCategory && scope.date === date ? 'active' : ''} key={treeKey(domain, subject, itemCategory, date)} onClick={() => onDateSelect(subject, itemCategory, date)}><span>{date}</span><small>{dateCount}</small></button>)}
                      </div>}
                    </div>
                  )
                })}
              </div>}
            </div>
          )
        })}
      </div>}
    </section>
  )
}

export function OverviewPage({ overview, onNavigate }) {
  if (!overview) return <LoadingState />
  const maxDomain = Math.max(...Object.values(overview.by_domain), 1)
  return (
    <div className="overview-page">
      <section className="summary-grid" aria-label="资料库摘要">
        <article className="summary-card"><span>集中资料</span><strong>{overview.records}</strong><p>可复用资料、原件与数据缓存</p></article>
        <article className="summary-card emphasis"><span>临时资料</span><strong>{overview.temporary_sources}</strong><p>均带采集或归档日期</p></article>
        <article className="summary-card"><span>正式报告</span><strong>{overview.reports}</strong><p>直接从 report/ 读取</p></article>
        <article className="summary-card"><span>最新同步</span><strong className="date-value">{shortDate(overview.latest_sync)}</strong><p>{overview.database_tables} 张数据表可预览</p></article>
      </section>
      <section className="overview-layout">
        <article className="surface domain-summary">
          <div className="section-heading"><div><h2>资料覆盖范围</h2><p>按领域统计集中数据层中的真实文件数量。</p></div><button className="text-button" onClick={() => onNavigate('library')}>查看资料库 <ArrowRight size={15} /></button></div>
          <div className="domain-bars">
            {Object.entries(overview.by_domain).filter(([, value]) => value > 0).map(([domain, value]) => (
              <div className="domain-row" key={domain}>
                <span>{DOMAIN_LABELS[domain]}</span>
                <div className="bar-track"><div className={`bar-fill ${domain}`} style={{ width: `${(value / maxDomain) * 100}%` }} /></div>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </article>
        <article className="surface workflow-note">
          <FolderArchive size={25} strokeWidth={1.6} />
          <h2>资料按类别管理</h2>
          <p>正式报告与资料归档分别保存；选择主题、子类和日期即可缩小查看范围。</p>
          <button className="button dark" onClick={() => onNavigate('library')}>浏览资料栏目 <ArrowRight size={16} /></button>
        </article>
      </section>
      <section className="surface sync-strip">
        <Database size={20} strokeWidth={1.7} />
        <div><strong>数据同步状态</strong><p>最近一次记录的同步时间：{formatDate(overview.latest_sync)}</p></div>
        <button className="text-button" onClick={() => onNavigate('data')}>查看样本表格 <ArrowRight size={15} /></button>
      </section>
    </div>
  )
}

export function LibraryPage({ notify, onChanged }) {
  const [records, setRecords] = useState([])
  const [labels, setLabels] = useState({ domains: DOMAIN_LABELS, kinds: KIND_LABELS })
  const [category, setCategory] = useState('reports')
  const [scope, setScope] = useState({ domain: '', subject: '', category: '', date: '' })
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [selected, setSelected] = useState(null)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingPreview, setLoadingPreview] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const params = new URLSearchParams()
    if (deferredSearch) params.set('search', deferredSearch)
    setLoading(true)
    get(`/api/records?${params.toString()}`, { signal: controller.signal })
      .then((payload) => {
        setRecords(payload.records)
        setLabels({
          domains: { ...DOMAIN_LABELS, ...payload.labels?.domains },
          kinds: { ...payload.labels?.kinds, ...KIND_LABELS },
        })
      })
      .catch((error) => { if (error.name !== 'AbortError') notify(error.message) })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [deferredSearch, notify])

  const categoryRecords = useMemo(() => records.filter((record) => recordGroup(record) === category), [category, records])
  const visibleRecords = useMemo(() => categoryRecords.filter((record) => (
    (!scope.domain || record.domain === scope.domain)
    && (!scope.subject || record.subject === scope.subject)
    && (!scope.category || record.category === scope.category)
    && (!scope.date || record.date === scope.date)
  )), [categoryRecords, scope])
  const activeMode = LIBRARY_MODES.find((mode) => mode.id === category) || LIBRARY_MODES[0]

  const changeCategory = (nextCategory) => {
    setCategory(nextCategory)
    setScope({ domain: '', subject: '', category: '', date: '' })
    setSelected(null)
    setPreview(null)
  }

  const changeScope = (nextScope) => {
    setScope(nextScope)
    setSelected(null)
    setPreview(null)
  }

  const selectRecord = async (record) => {
    setSelected(record)
    setLoadingPreview(true)
    try {
      setPreview(await get(`/api/records/${record.id}/preview`))
    } catch (error) {
      notify(error.message)
    } finally {
      setLoadingPreview(false)
    }
  }

  const queueForCuration = async () => {
    if (!selected) return
    try {
      await post(`/api/records/${selected.id}/wiki-queue`, {})
      setRecords((items) => items.map((item) => (item.id === selected.id ? { ...item, wiki_queued: true } : item)))
      setSelected((current) => ({ ...current, wiki_queued: true }))
      notify('已加入待沉淀队列，原件已复制到 Wiki Raw。')
    } catch (error) { notify(error.message) }
  }

  const cancelCuration = async () => {
    if (!selected) return
    try {
      const result = await del(`/api/records/${selected.id}/wiki-queue`)
      setRecords((items) => items.map((item) => (item.id === selected.id ? { ...item, wiki_queued: false } : item)))
      setSelected((current) => ({ ...current, wiki_queued: false }))
      notify(result.message)
    } catch (error) { notify(error.message) }
  }

  const moveToTrash = async () => {
    if (!selected || !window.confirm(`将“${selected.title}”移至集中数据层回收区？\n\n该资料将不再出现在资料库中。`)) return
    try {
      const result = await post(`/api/records/${selected.id}/trash`, {})
      notify(result.message)
      setSelected(null)
      setPreview(null)
      onChanged()
      setRecords((items) => items.filter((item) => item.id !== selected.id))
    } catch (error) { notify(error.message) }
  }

  return (
    <div className="library-page">
      <section className="toolbar library-toolbar surface">
        <div className="search-field"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索主题、文件名或研究类型" /></div>
        <div className="library-toolbar-meta"><span className="mode-indicator">{activeMode.label}</span><span className="result-count">{visibleRecords.length} 条结果</span></div>
      </section>
      <section className="library-layout surface">
        <LibraryTree category={category} records={categoryRecords} allRecords={records} scope={scope} onCategoryChange={changeCategory} onScopeChange={changeScope} />
        <div className="record-list">
          <div className="list-heading"><div><span>资料清单</span><h2>{activeMode.label}</h2></div><div className="scope-summary"><span>{scopeLabel(scope)}</span>{scope.domain && <button type="button" onClick={() => changeScope({ domain: '', subject: '', category: '', date: '' })}>清除筛选</button>}</div></div>
          {loading ? <LoadingState /> : visibleRecords.length === 0 ? <EmptyState title="没有匹配的资料" description="可切换资料类别、选择其他主题日期，或清空搜索词重新查看。" /> : (
            <div className="record-table-wrap"><table className="record-table"><thead><tr><th>主题与文件</th><th>领域</th><th>子类</th><th>状态</th><th>日期</th></tr></thead><tbody>{visibleRecords.map((record) => (
              <tr key={record.id} className={selected?.id === record.id ? 'selected' : ''} onClick={() => selectRecord(record)}>
                <td><strong>{record.title}</strong><span>{record.subject} · {record.extension.toUpperCase()} · {formatSize(record.size)}</span></td>
                <td>{labels.domains[record.domain]}</td><td>{record.category || '未分类'}</td><td><span className={`type-label ${record.kind}`}>{labels.kinds[record.kind]}</span></td><td>{record.date}</td>
              </tr>
            ))}</tbody></table></div>
          )}
        </div>
        <aside className="record-preview">
          {!selected ? <EmptyState title="选择一条资料" description="右侧会展示正文、文件属性与下一步处理方式。" icon={FileText} /> : (
            <>
              <div className="preview-heading"><div><span className={`type-label ${selected.kind}`}>{labels.kinds[selected.kind]}</span><h2>{selected.title}</h2><p>{labels.domains[selected.domain]} · {selected.subject} · {selected.category || '未分类'} · {selected.date}</p></div></div>
              <dl className="file-details"><div><dt>文件类型</dt><dd>{selected.extension.toUpperCase()}</dd></div><div><dt>资料子类</dt><dd>{selected.category || '未分类'}</dd></div><div><dt>迁移来源</dt><dd>{selected.origin}</dd></div><div><dt>更新时间</dt><dd>{formatDate(selected.updated_at)}</dd></div></dl>
              <div className="preview-body">{loadingPreview ? <LoadingState /> : preview?.preview?.kind === 'text' ? <pre>{preview.preview.content}{preview.preview.truncated ? '\n\n… 内容过长，当前仅显示前段。' : ''}</pre> : <EmptyState title="保留原始文件" description={preview?.preview?.content || '该资料没有可直接预览的文本。'} />}</div>
              {selected.storage === 'report' ? <p className="preview-path">此正式报告来自 <code>report/{selected.path}</code>。</p> : <div className="preview-actions">{selected.wiki_queued ? <button className="button secondary" onClick={cancelCuration}><X size={16} /> 取消待沉淀</button> : <button className="button secondary" onClick={queueForCuration}><UploadCloud size={16} /> 加入待沉淀队列</button>}<button className="button danger" onClick={moveToTrash}><Trash2 size={16} /> 移至回收区</button></div>}
            </>
          )}
        </aside>
      </section>
    </div>
  )
}

function dataSyncMessage(sync) {
  return sync?.message || '更新个股日线、估值与股票基础信息。'
}

export function DataPage() {
  const [tables, setTables] = useState([])
  const [selected, setSelected] = useState(null)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [sync, setSync] = useState({ state: 'idle' })
  const [syncing, setSyncing] = useState(false)
  const refreshTables = useCallback(async () => {
    const payload = await get('/api/data/tables')
    setTables(payload.tables)
    setSelected((current) => payload.tables.some((table) => table.name === current) ? current : payload.tables[0]?.name ?? null)
  }, [])
  const syncLatestData = useCallback(async () => {
    try {
      const payload = await post('/api/data/sync', {})
      setSync(payload.sync)
      const isRunning = payload.sync?.state === 'running'
      setSyncing(isRunning)
      if (!isRunning) {
        await refreshTables()
        setRefreshVersion((version) => version + 1)
      }
    } catch (currentError) {
      setSync({ state: 'error', message: currentError.message })
      setSyncing(false)
    }
  }, [refreshTables])
  useEffect(() => { refreshTables().catch((currentError) => setError(currentError.message)) }, [refreshTables])
  useEffect(() => {
    if (!selected) return undefined
    let cancelled = false
    setPreview(null)
    get(`/api/data/tables/${selected}`).then((payload) => { if (!cancelled) setPreview(payload) }).catch((currentError) => { if (!cancelled) setError(currentError.message) })
    return () => { cancelled = true }
  }, [refreshVersion, selected])
  useEffect(() => {
    if (!syncing) return undefined
    let cancelled = false
    const poll = async () => {
      try {
        const payload = await get('/api/data/sync')
        if (cancelled) return
        setSync(payload.sync)
        if (payload.sync?.state !== 'running') {
          setSyncing(false)
          if (payload.sync?.state === 'success') {
            await refreshTables()
            if (!cancelled) setRefreshVersion((version) => version + 1)
          }
        }
      } catch (currentError) {
        if (!cancelled) {
          setSync({ state: 'error', message: currentError.message })
          setSyncing(false)
        }
      }
    }
    poll()
    const timer = window.setInterval(poll, 2000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [refreshTables, syncing])
  if (error) return <EmptyState title="无法读取同步数据" description={error} icon={Database} />
  if (!tables.length) return <LoadingState />
  return (
    <section className="data-layout surface">
      <aside className="data-nav"><h2>可用数据表</h2><p>选择表名即可查看字段和前几行样本。</p><button type="button" className="data-sync-button" onClick={syncLatestData} disabled={syncing || sync.state === 'running'}><RefreshCw className={syncing ? 'spin' : ''} size={15} />{syncing ? '正在同步' : '同步最新数据'}</button><p className={`data-sync-status ${sync.state}`}>{dataSyncMessage(sync)}</p>{tables.map((table) => <button key={table.name} className={selected === table.name ? 'active' : ''} onClick={() => setSelected(table.name)}><span>{table.label}</span><small>{table.rows.toLocaleString()} 行</small></button>)}</aside>
      <div className="data-preview">{!preview ? <LoadingState /> : <><div className="data-heading"><div><h2>{preview.label}</h2><p>数据时点：{shortDate(preview.latest_data)}　·　最近同步：{formatDate(preview.latest_sync)}</p></div><span>{preview.rows.length} 行样本</span></div><div className="data-table-wrap"><table className="data-table"><thead><tr>{preview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{preview.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div></>}</div>
    </section>
  )
}

const profileFields = [
  ['horizon', '主要持有期', ['长期（多年）', '中期（3–6个月）', '短期（一个月内）']],
  ['style', '核心投资方法', ['质量成长', '价值与安全边际', '周期与景气', '事件驱动', '指数化与资产配置']],
  ['risk_tolerance', '风险承受度', ['保守', '平衡', '进取']],
  ['review_cadence', '复盘节奏', ['财报与重大事件后', '每月', '每季度', '按需']],
]

function emptyHolding() {
  return { symbol: '', name: '', quantity: '', average_cost: '', latest_price: '', target_weight: '', notes: '' }
}

function emptyTrade() {
  return { date: '', side: 'buy', symbol: '', name: '', quantity: '', price: '', fees: '', realized_pnl: '', notes: '' }
}

export function ProfilePage({ notify }) {
  const [profile, setProfile] = useState({ holdings: [], trades: [] })
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    get('/api/profile')
      .then((payload) => setProfile({ ...payload, holdings: Array.isArray(payload.holdings) ? payload.holdings : [], trades: Array.isArray(payload.trades) ? payload.trades : [] }))
      .catch((error) => notify(error.message))
  }, [notify])
  const holdings = profile.holdings || []
  const trades = profile.trades || []
  const summary = useMemo(() => ({
    holdings: holdings.length,
    unrealizedPnl: holdings.reduce((total, holding) => total + (calculateHoldingPnl(holding) || 0), 0),
    trades: trades.length,
    realizedPnl: trades.reduce((total, trade) => total + (toNumber(trade.realized_pnl) || 0), 0),
  }), [holdings, trades])
  const update = (key, value) => setProfile((current) => ({ ...current, [key]: value }))
  const updateEntry = (collection, index, key, value) => setProfile((current) => ({
    ...current,
    [collection]: current[collection].map((entry, currentIndex) => currentIndex === index ? { ...entry, [key]: value } : entry),
  }))
  const addEntry = (collection, entry) => setProfile((current) => ({ ...current, [collection]: [...current[collection], entry] }))
  const removeEntry = (collection, index) => setProfile((current) => ({ ...current, [collection]: current[collection].filter((entry, currentIndex) => currentIndex !== index) }))
  const save = async (event) => {
    event.preventDefault()
    try {
      const payload = await post('/api/profile', profile)
      setProfile(payload)
      setSaved(true)
      notify('投资风格、持仓与交易记录已保存到集中数据层。')
    } catch (error) { notify(error.message) }
  }
  return (
    <form className="profile-form surface" onSubmit={save}>
      <section className="profile-section">
        <div className="section-heading"><div><h2>研究偏好</h2><p>帮助 Agent 理解你的持有期、方法与风险约束。</p></div></div>
        <div className="form-grid">{profileFields.map(([key, label, options]) => <label key={key}><span>{label}</span><select value={profile[key] ?? ''} onChange={(event) => update(key, event.target.value)}><option value="">请选择</option>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>)}</div>
        <label><span>重点关注行业或主题</span><input value={profile.focus_sectors ?? ''} onChange={(event) => update('focus_sectors', event.target.value)} placeholder="例如：高端制造、半导体、出海消费" /></label>
        <label><span>回避项或明确约束</span><input value={profile.avoid ?? ''} onChange={(event) => update('avoid', event.target.value)} placeholder="例如：高杠杆、流动性不足、无法核验的题材" /></label>
        <label><span>研究与决策备注</span><textarea value={profile.notes ?? ''} onChange={(event) => update('notes', event.target.value)} placeholder="记录你希望长期沿用的研究原则、证据要求与复盘方式。" /></label>
      </section>
      <section className="profile-section portfolio-section">
        <div className="section-heading"><div><h2>当前持仓</h2><p>填写数量、成本和最新价格后，界面会计算浮动盈亏；这些数字以你最后保存的时点为准。</p></div><button type="button" className="button secondary" onClick={() => addEntry('holdings', emptyHolding())}><Plus size={16} /> 新增持仓</button></div>
        <div className="portfolio-summary"><div><span>持仓数量</span><strong>{summary.holdings}</strong></div><div><span>已填写浮盈亏</span><strong className={summary.unrealizedPnl >= 0 ? 'positive' : 'negative'}>{formatMoney(summary.unrealizedPnl)}</strong></div><div><span>交易笔数</span><strong>{summary.trades}</strong></div><div><span>已实现盈亏</span><strong className={summary.realizedPnl >= 0 ? 'positive' : 'negative'}>{formatMoney(summary.realizedPnl)}</strong></div></div>
        {holdings.length === 0 ? <EmptyState title="尚未填写持仓" description="新增持仓后，后续持仓复盘可以读取成本、数量和当前盈亏。" /> : <div className="entry-stack">{holdings.map((holding, index) => <article className="entry-card" key={`holding-${index}`}><div className="entry-card-heading"><strong>持仓 {index + 1}</strong><button type="button" className="icon-button" aria-label={`删除持仓 ${index + 1}`} onClick={() => removeEntry('holdings', index)}><Trash2 size={15} /></button></div><div className="entry-grid holdings-grid"><label><span>证券代码</span><input value={holding.symbol ?? ''} onChange={(event) => updateEntry('holdings', index, 'symbol', event.target.value)} placeholder="例如：600519.SH" /></label><label><span>证券名称</span><input value={holding.name ?? ''} onChange={(event) => updateEntry('holdings', index, 'name', event.target.value)} placeholder="例如：贵州茅台" /></label><label><span>持仓数量</span><input inputMode="decimal" type="number" value={holding.quantity ?? ''} onChange={(event) => updateEntry('holdings', index, 'quantity', event.target.value)} /></label><label><span>持仓均价</span><input inputMode="decimal" type="number" step="0.0001" value={holding.average_cost ?? ''} onChange={(event) => updateEntry('holdings', index, 'average_cost', event.target.value)} /></label><label><span>最新价格</span><input inputMode="decimal" type="number" step="0.0001" value={holding.latest_price ?? ''} onChange={(event) => updateEntry('holdings', index, 'latest_price', event.target.value)} /></label><label><span>目标仓位（%）</span><input inputMode="decimal" type="number" step="0.1" value={holding.target_weight ?? ''} onChange={(event) => updateEntry('holdings', index, 'target_weight', event.target.value)} /></label><label className="wide"><span>持仓备注</span><input value={holding.notes ?? ''} onChange={(event) => updateEntry('holdings', index, 'notes', event.target.value)} placeholder="例如：核心逻辑、计划持有期、下次复核条件" /></label><div className="pnl-field"><span>浮动盈亏</span><strong className={(calculateHoldingPnl(holding) || 0) >= 0 ? 'positive' : 'negative'}>{calculateHoldingPnl(holding) === null ? '待填写价格' : formatMoney(calculateHoldingPnl(holding))}</strong></div></div></article>)}</div>}
      </section>
      <section className="profile-section portfolio-section">
        <div className="section-heading"><div><h2>交易与盈亏记录</h2><p>逐笔记录买卖、费用与已实现盈亏，让 Agent 在复盘时可以看到真实交易背景。</p></div><button type="button" className="button secondary" onClick={() => addEntry('trades', emptyTrade())}><Plus size={16} /> 新增交易</button></div>
        {trades.length === 0 ? <EmptyState title="尚未填写交易记录" description="记录买入、卖出与已实现盈亏后，可用于后续的交易复盘。" /> : <div className="entry-stack">{trades.map((trade, index) => <article className="entry-card" key={`trade-${index}`}><div className="entry-card-heading"><strong>交易 {index + 1}</strong><button type="button" className="icon-button" aria-label={`删除交易 ${index + 1}`} onClick={() => removeEntry('trades', index)}><Trash2 size={15} /></button></div><div className="entry-grid trades-grid"><label><span>交易日期</span><input type="date" value={trade.date ?? ''} onChange={(event) => updateEntry('trades', index, 'date', event.target.value)} /></label><label><span>方向</span><select value={trade.side ?? 'buy'} onChange={(event) => updateEntry('trades', index, 'side', event.target.value)}><option value="buy">买入</option><option value="sell">卖出</option></select></label><label><span>证券代码</span><input value={trade.symbol ?? ''} onChange={(event) => updateEntry('trades', index, 'symbol', event.target.value)} placeholder="例如：000001.SZ" /></label><label><span>证券名称</span><input value={trade.name ?? ''} onChange={(event) => updateEntry('trades', index, 'name', event.target.value)} /></label><label><span>成交数量</span><input inputMode="decimal" type="number" value={trade.quantity ?? ''} onChange={(event) => updateEntry('trades', index, 'quantity', event.target.value)} /></label><label><span>成交价格</span><input inputMode="decimal" type="number" step="0.0001" value={trade.price ?? ''} onChange={(event) => updateEntry('trades', index, 'price', event.target.value)} /></label><label><span>费用</span><input inputMode="decimal" type="number" step="0.01" value={trade.fees ?? ''} onChange={(event) => updateEntry('trades', index, 'fees', event.target.value)} /></label><label><span>已实现盈亏</span><input inputMode="decimal" type="number" step="0.01" value={trade.realized_pnl ?? ''} onChange={(event) => updateEntry('trades', index, 'realized_pnl', event.target.value)} /></label><label className="wide"><span>交易备注</span><input value={trade.notes ?? ''} onChange={(event) => updateEntry('trades', index, 'notes', event.target.value)} placeholder="例如：交易理由、偏差、复盘结论" /></label></div></article>)}</div>}
      </section>
      <div className="form-footer"><p>所有资料仅保存到 <code>data/research-library/settings/investor-profile.json</code>。持仓与盈亏仅作为你提供的本地研究上下文，不会自动更新或写入报告。</p><button className="button primary" type="submit">{saved ? '再次保存全部资料' : '保存投资风格与交易记录'}</button></div>
    </form>
  )
}

export function SettingsPage({ notify }) {
  const [fields, setFields] = useState([])
  const [values, setValues] = useState({})
  useEffect(() => { get('/api/settings').then((payload) => setFields(payload.fields)).catch((error) => notify(error.message)) }, [notify])
  const save = async (event) => {
    event.preventDefault()
    const updates = Object.fromEntries(Object.entries(values).filter(([, value]) => value))
    try {
      const payload = await post('/api/settings', { updates })
      setFields(payload.fields)
      setValues({})
      notify('TuShare Token 已写入项目本地 .env。')
    } catch (error) { notify(error.message) }
  }
  return <form className="settings-form surface" onSubmit={save}><div className="settings-intro"><h2>TuShare Token</h2><p>已有 Token 只显示保存状态，留空不会覆盖；输入新值后保存即可。</p></div>{fields.map((field) => <label className="setting-row" key={field.key}><div><strong>{field.key}</strong><span>{field.has_value ? '已保存本地值' : '尚未配置'}</span></div><input type="password" value={values[field.key] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))} placeholder={field.has_value ? '留空可保留现有 Token' : '输入 Token 后保存'} /></label>)}<div className="form-footer"><p>Token 不会写入报告、数据库预览、交易记录或其他界面字段。</p><button className="button primary" type="submit">保存 TuShare Token</button></div></form>
}
