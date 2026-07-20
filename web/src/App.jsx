import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { get } from './api'
import { LoadingState, Notice, PageHeader, Sidebar } from './components'
import { DataPage, LibraryPage, OverviewPage, ProfilePage, SettingsPage, WatchlistPage } from './pages'

const pageCopy = {
  overview: ['总览', '从一个视图了解本地资料、同步数据与研究偏好。'],
  library: ['研究资料与报告', '正式报告从 report/ 读取；归档资料和原件保留在集中数据层，按领域、主题和日期浏览。'],
  data: ['同步数据', '以可读表格查看当前已同步的数据、覆盖时点与前几行样本。'],
  watchlist: ['研究跟踪池', '保存 Agent 推荐且值得继续研究的股票，并沿用原研究路径、逻辑与复核条件。'],
  profile: ['投资风格与交易记录', '保存研究偏好、当前持仓和已实现盈亏；这些内容只保留在集中数据层。'],
  settings: ['环境设置', '在项目本地 .env 保存 TuShare Token，密钥不会回显。'],
}

export default function App() {
  const [page, setPage] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')

  const refreshOverview = useCallback(async () => {
    try {
      setLoading(true)
      setOverview(await get('/api/overview'))
    } catch (error) {
      setNotice(error.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refreshOverview() }, [refreshOverview])

  const action = page === 'overview' ? (
    <button className="button secondary" onClick={refreshOverview}>
      <RefreshCw size={16} /> 刷新概览
    </button>
  ) : null

  const renderPage = () => {
    if (loading && !overview) return <LoadingState />
    if (page === 'overview') return <OverviewPage overview={overview} onNavigate={setPage} />
    if (page === 'library') return <LibraryPage notify={setNotice} onChanged={refreshOverview} />
    if (page === 'data') return <DataPage />
    if (page === 'watchlist') return <WatchlistPage notify={setNotice} />
    if (page === 'profile') return <ProfilePage notify={setNotice} />
    return <SettingsPage notify={setNotice} />
  }

  return (
    <div className="app-shell">
      <Sidebar page={page} onNavigate={setPage} />
      <main className="main-content">
        <PageHeader title={pageCopy[page][0]} description={pageCopy[page][1]} action={action} />
        <Notice message={notice} onDismiss={() => setNotice('')} />
        {renderPage()}
      </main>
    </div>
  )
}
