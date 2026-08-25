// 绞杀者迁移期间的根组件：Phase 2a 起逐个视图替换为真实实现
export function BootPlaceholder({ sessionId }: { sessionId: string | null }) {
  return (
    <main className="boot-empty">
      {sessionId ? `session ${sessionId}` : 'ATA'}
    </main>
  )
}
