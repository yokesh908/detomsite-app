const getSupabaseConfig = () => {
  const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
  const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
  return { url, anonKey }
}

export const isSupabaseConfigured = () => {
  const { url, anonKey } = getSupabaseConfig()
  return Boolean(url && anonKey && url.includes('supabase.co'))
}

export async function syncProfileToSupabase(profile: { id: string; email: string; name: string; role: string }) {
  const { url, anonKey } = getSupabaseConfig()

  if (!isSupabaseConfigured() || !url || !anonKey) return null

  const response = await fetch(`${url}/rest/v1/profiles`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      apikey: anonKey,
      Authorization: `Bearer ${anonKey}`,
      // Don't error when the same profile already exists (re-logins)
      Prefer: 'resolution=ignore-duplicates',
    },
    body: JSON.stringify({
      id: profile.id,
      email: profile.email,
      name: profile.name,
      role: profile.role,
      created_at: new Date().toISOString(),
    }),
  })

  if (!response.ok) {
    throw new Error('Unable to sync profile to Supabase')
  }

  return response.json()
}
