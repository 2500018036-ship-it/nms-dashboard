import { BrowserRouter } from 'react-router'
import { AuthProvider } from './data/AuthContext.jsx'
import { AppRouter } from './app/router'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRouter />
      </AuthProvider>
    </BrowserRouter>
  )
}
