import { isSupabaseConfigured } from './supabase'

export async function testSupabaseConnection() {
  if (!isSupabaseConfigured()) {
    return { ok: false, message: 'Supabase env vars are not configured yet.' }
  }

  const url = import.meta.env.VITE_SUPABASE_URL as string
  const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string

  const response = await fetch(`${url}/rest/v1/profiles?select=id`, {
    headers: {
      apikey: anonKey,
      Authorization: `Bearer ${anonKey}`,
    },
  })

  if (!response.ok) {
    return { ok: false, message: `Supabase request failed: ${response.status}` }
  }

  return { ok: true, message: 'Supabase connection is working.' }
}
