import {
  Archive,
  BarChart3,
  Database,
  FileClock,
  FileText,
  FolderArchive,
  ListChecks,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'

export const navigation = [
  { id: 'overview', label: '总览', icon: BarChart3 },
  { id: 'library', label: '集中资料库', icon: FolderArchive },
  { id: 'data', label: '同步数据', icon: Database },
  { id: 'watchlist', label: '研究跟踪池', icon: ListChecks },
  { id: 'profile', label: '投资风格与交易', icon: SlidersHorizontal },
  { id: 'settings', label: '环境设置', icon: Settings2 },
]

export function Sidebar({ page, onNavigate }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true"><span>IR</span></div>
        <div>
          <strong>Research Hub</strong>
          <small>本地投研工作台</small>
        </div>
      </div>
      <nav aria-label="主导航">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button className={`nav-item ${page === id ? 'active' : ''}`} key={id} onClick={() => onNavigate(id)}>
            <Icon size={18} strokeWidth={1.8} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-note">
        <Archive size={17} strokeWidth={1.7} />
        <p>正式报告、研究跟踪池、归档资料、持仓记录和数据缓存均保存在本机，便于持续研究与复盘。</p>
      </div>
    </aside>
  )
}

export function PageHeader({ title, description, action }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </header>
  )
}

export function EmptyState({ title, description, icon: Icon = FileText }) {
  return (
    <div className="empty-state">
      <Icon size={28} strokeWidth={1.5} />
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  )
}

export function LoadingState() {
  return <div className="loading"><RefreshCw size={18} className="spin" /> 正在读取本地资料…</div>
}

export function Notice({ message, onDismiss }) {
  if (!message) return null
  return (
    <div className="notice" role="status">
      <span>{message}</span>
      <button aria-label="关闭提示" onClick={onDismiss}><X size={16} /></button>
    </div>
  )
}

export const icons = { Search, FileClock, FileText, Trash2, UploadCloud }
