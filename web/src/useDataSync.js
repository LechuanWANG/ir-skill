import { useCallback, useEffect, useState } from 'react'
import { get, post } from './api'

const POLL_INTERVAL_MS = 2000

export function useDataSync() {
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

  useEffect(() => {
    refreshTables().catch((currentError) => setError(currentError.message))
  }, [refreshTables])

  useEffect(() => {
    if (!selected) return undefined
    let cancelled = false
    setPreview(null)
    get(`/api/data/tables/${encodeURIComponent(selected)}`)
      .then((payload) => { if (!cancelled) setPreview(payload) })
      .catch((currentError) => { if (!cancelled) setError(currentError.message) })
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
    const timer = window.setInterval(poll, POLL_INTERVAL_MS)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [refreshTables, syncing])

  return { error, preview, selected, setSelected, sync, syncLatestData, syncing, tables }
}
