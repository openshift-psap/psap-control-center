import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { fournosApi } from '../services/api'
import TestingJobDetail from './TestingJobDetail'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it.each([
  [{ name: 'demo', namespace: 'original' }, 'original'],
  [{ name: 'demo' }, 'Not recorded'],
] as const)('shows the archived namespace or an explicit missing value', async (metadata, expected) => {
  vi.spyOn(fournosApi, 'getJob').mockResolvedValue({
    job: { metadata, source: 'history', status: { phase: 'Succeeded' }, spec: {} },
    pods: [], stages: [], forge_info: { project: 'demo', args: [], config_overrides: {} },
  })
  render(<QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={['/testing/jobs/demo']}>
      <Routes><Route path="/testing/jobs/:name" element={<TestingJobDetail />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>)
  const label = await screen.findByText('Namespace')
  expect(label.nextElementSibling).toHaveTextContent(expected)
})
