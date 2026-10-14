import {useEffect, useState} from 'react'
import {Power} from 'lucide-react'
import {api} from '../api/client'
import {useConnection} from '../app/context'
import {ErrorBox, Modal} from './ui'

/** 关闭当前安装后台；与停止单个调度器的按钮分开。 */
export function LocalShutdown() {
  const connection = useConnection()
  const [available, setAvailable] = useState(false)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (connection !== 'ready' || document.documentElement.dataset.localDesktop === 'true') return
    let active = true
    void api.request('system.localStatus', {}).then(result => {
      if (active) setAvailable(result.shutdownAvailable)
    }).catch(() => {if (active) setAvailable(false)})
    return () => {active = false}
  }, [connection])
  if (!available || document.documentElement.dataset.localDesktop === 'true') return null
  async function close() {
    setBusy(true); setError('')
    try {
      const result = await api.request('system.shutdown', {confirm: true})
      setAccepted(result.accepted)
    } catch (exception) {setError((exception as Error).message); setBusy(false)}
  }
  return <>
    <button className="local-shutdown-button text-button" disabled={busy || connection !== 'ready'} onClick={() => setOpen(true)}><Power size={16}/><span>关闭程序</span></button>
    {open && <Modal title={accepted ? '正在关闭后台' : '关闭 AzurPilot 后台？'} onClose={() => {if (!busy) setOpen(false)}}>
      <p>{accepted ? (connection === 'offline' ? '关闭请求已接受，连接已断开。游戏与模拟器保留。' : '关闭请求已接受，正在停止任务和辅助服务…') : '正在运行的任务将停止，游戏与模拟器保留。'}</p>
      {error && <ErrorBox message={error}/>}
      {!accepted && <div className="button-row"><button className="text-button" disabled={busy} onClick={() => setOpen(false)}>取消</button><button disabled={busy} onClick={() => void close()}>{busy ? '正在请求…' : '关闭后台'}</button></div>}
    </Modal>}
  </>
}
