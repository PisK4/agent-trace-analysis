import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BootPlaceholder } from './components/BootPlaceholder'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BootPlaceholder sessionId={null} />
  </StrictMode>,
)
