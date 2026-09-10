import api from './api'
import { LocalSession } from '../utils/session'

export async function saveSessionToBackend(session: LocalSession) {
  try {
    await api.post('/local/sessions', session)
  } catch {
    // Local browser session keeps the app usable when the backend is offline.
  }
}
