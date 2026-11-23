import React from 'react'
import ReactDOM from 'react-dom/client'
import { ClerkProvider } from '@clerk/react'
import App from './App.jsx'
import './index.css'

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {publishableKey ? (
      <ClerkProvider publishableKey={publishableKey}>
        <App />
      </ClerkProvider>
    ) : (
      <div className="setup-notice">
        <h1>Contract Review Assistant</h1>
        <p>
          The Clerk publishable key is missing. Copy <code>.env.example</code> to{' '}
          <code>frontend/.env.local</code>, set <code>VITE_CLERK_PUBLISHABLE_KEY</code>, and
          restart. See the README for how to create a Clerk application.
        </p>
      </div>
    )}
  </React.StrictMode>,
)
