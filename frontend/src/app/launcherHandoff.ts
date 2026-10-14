import {useEffect} from 'react'

/** 两种原生启动方式共用的首屏通知；普通网页访问不创建请求。 */
export function useLauncherHandoff(connection: string, instancesLoaded: boolean, schemaLoaded: boolean) {
  useEffect(() => {
    const url = new URL(window.location.href)
    const ticket = url.searchParams.get('launcher_handoff')
    if (!ticket || !/^[0-9a-f]{32}$/.test(ticket)) return
    if (connection !== 'auth' && !(connection === 'ready' && instancesLoaded && schemaLoaded)) return
    let active = true, frame = 0, attempts = 0, retry: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    const acknowledge = async () => {
      attempts += 1
      try {
        const response = await fetch(new URL('api/local-launcher/handoff', document.baseURI), {
          method: 'POST', credentials: 'same-origin', signal: controller.signal,
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ticket, stage: connection === 'auth' ? 'auth' : 'ready'}),
        })
        if (!response.ok) throw new Error('交接尚未确认')
        if (active) {
          const current = new URL(window.location.href)
          if (current.searchParams.get('launcher_handoff') === ticket) {
            current.searchParams.delete('launcher_handoff')
            window.history.replaceState(window.history.state, '', current)
          }
        }
      } catch {
        if (active && attempts < 50) retry = setTimeout(() => void acknowledge(), 1500)
      }
    }
    const waitForContent = () => {
      const content = document.querySelector('#main-content') ?? document.getElementById('root')
      const loading = content && [...content.querySelectorAll<HTMLElement>('.loading')].some(node => node.offsetWidth > 0 && node.offsetHeight > 0)
      if (!content?.childElementCount || (connection !== 'auth' && loading)) {
        if (active) retry = setTimeout(waitForContent, 100)
        return
      }
      // 业务页结束加载且经过两次绘制机会后，再让启动器开始交接动画。
      frame = requestAnimationFrame(() => {frame = requestAnimationFrame(() => void acknowledge())})
    }
    waitForContent()
    return () => {active = false; controller.abort(); cancelAnimationFrame(frame); clearTimeout(retry)}
  }, [connection, instancesLoaded, schemaLoaded])
}
