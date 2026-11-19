// ─── 30-minute slot grid helpers ────────────────────────────────────────

export const SLOT_MINUTES = 30
export const SLOTS_PER_DAY = (24 * 60) / SLOT_MINUTES

export function slotIndexFor(hour: number, minute: number): number {
  return Math.floor((hour * 60 + minute) / SLOT_MINUTES)
}

export function slotStart(index: number): { hour: number; minute: number } {
  const totalMinutes = index * SLOT_MINUTES
  return { hour: Math.floor(totalMinutes / 60), minute: totalMinutes % 60 }
}

export function slotLabel(index: number): string {
  const { hour, minute } = slotStart(index)
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}
