import { usePolling } from '../shared/data/usePolling'
import { useServices } from './services'

// Ordinary reads have an independent, lower-frequency budget than live games.
// Callers own cancellation, identity boundaries, and protection of local drafts.
export function useAutoRefresh(
  read: () => Promise<void>,
  enabled: () => boolean = () => true,
  intervalMs = 30000,
) {
  const services = useServices()
  return usePolling(
    read,
    () =>
      services.navigationMenu.value === null && services.userMenuTarget.value === null && enabled(),
    intervalMs,
  )
}
