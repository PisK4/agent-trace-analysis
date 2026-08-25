import { useCallback, useRef, useState, type ReactNode } from 'react'
import { ToastContext } from './toast'

interface ToastItem { id: number; msg: string; kind: 'ok' | 'err' }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(0)

  const push = useCallback((msg: string, kind: 'ok' | 'err' = 'ok') => {
    const id = ++nextId.current
    setItems((prev) => [...prev, { id, msg, kind }])
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 2400)
  }, [])

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="log" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} role="status">{t.msg}</div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
