// 写操作反馈通道的 context 与 hook：组件（ToastProvider）在 ToastProvider.tsx。
// 拆文件只为 fast-refresh 约束：本文件不含组件，可安全导出函数。
import { createContext, useContext } from 'react'

export type ToastFn = (msg: string, kind?: 'ok' | 'err') => void

export const ToastContext = createContext<ToastFn>(() => {})

export const useToast = () => useContext(ToastContext)
