import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { expect, it } from 'vitest'
import Layout from './Layout'

function CurrentLocation() {
  const { pathname, search } = useLocation()
  return <output aria-label="Current location">{pathname}{search}</output>
}

it('toggles Testing from its label without leaving the current view, and navigates from Jobs', () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(['auth-config'], { google_enabled: true, local_login_enabled: false })
  client.setQueryData(['hearthStatus'], { configured: false, available: false })

  render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={['/testing?tab=queued']}>
      <Layout />
      <CurrentLocation />
    </MemoryRouter>
  </QueryClientProvider>)
  const location = screen.getByLabelText('Current location')

  fireEvent.click(screen.getByText('Testing', { exact: true }))
  expect(location).toHaveTextContent('/testing?tab=queued')
  const toggle = screen.getByRole('button', { name: 'Expand Testing' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('link', { name: 'Jobs' })).toBeNull()

  fireEvent.click(toggle)
  expect(toggle).toHaveAccessibleName('Collapse Testing')
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.queryByRole('link', { name: 'Testing' })).toBeNull()
  const jobs = screen.getByRole('link', { name: 'Jobs' })
  expect(jobs).toHaveAttribute('aria-current', 'page')
  fireEvent.click(jobs)
  expect(location).toHaveTextContent('/testing?tab=live')
})
