export function webLink(value?: string) {
  if (!value) return
  try {
    const url = new URL(value)
    if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) return url.href
  } catch { /* Ignore malformed links in historical records. */ }
}
