import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AgentProvider } from './context/AgentContext'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AgentProvider>
        <App />
      </AgentProvider>
    </BrowserRouter>
  </StrictMode>,
)
