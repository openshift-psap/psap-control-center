import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fournosApi } from '../services/api'
import JobResultLinks from './JobResultLinks'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const runRoute = '/experiments/5/runs/1234567890abcdef1234567890abcdef'

function show(runUrl = 'https://mlflow.example/base/#' + runRoute + '/artifacts?workspace=team') {
  render(<QueryClientProvider client={new QueryClient()}>
    <JobResultLinks job="demo" runUrl={runUrl} ciUrl="https://ci.example/artifacts" />
  </QueryClientProvider>)
}

it('browses on demand, opens files as plain text, and remembers the folder across collapse', async () => {
  const list = vi.spyOn(fournosApi, 'getMlflowDirectory').mockImplementation(async (_job, path, token) =>
    path ? { files: [{ path: 'stage/status.yaml', file_size: 55, is_dir: false }], next_page_token: null }
      : token ? { files: [{ path: 'large.json', file_size: 1_000_000, is_dir: false }], next_page_token: null }
        : { files: [{ path: 'stage', is_dir: true, file_size: null }], next_page_token: 'next' })
  const preview = vi.spyOn(fournosApi, 'getMlflowPreview').mockResolvedValue({ text: '<b>success</b>' })
  show()
  const toggle = screen.getByRole('button', { name: 'Explore files' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(list).not.toHaveBeenCalled()
  fireEvent.click(toggle)
  await screen.findByRole('button', { name: 'stage/' })
  fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
  fireEvent.click(await screen.findByRole('button', { name: 'large.json' }))
  expect(screen.getByText(/exceeds the 64 KiB/)).toBeVisible()
  const fileLink = screen.getByRole('link', { name: 'Open this file in MLflow' })
  expect(fileLink).toHaveAttribute('href', 'https://mlflow.example/base/#' + runRoute + '/artifacts/large.json?workspace=team')
  expect(fileLink).toHaveAttribute('target', '_blank')
  expect(preview).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'stage/' }))
  fireEvent.click(await screen.findByRole('button', { name: 'status.yaml' }))
  expect(await screen.findByText('<b>success</b>')).toBeVisible()
  expect(preview).toHaveBeenCalledWith('demo', 'stage/status.yaml', expect.any(AbortSignal))
  fireEvent.click(toggle)
  expect(screen.queryByRole('region', { name: 'MLflow artifacts' })).toBeNull()
  fireEvent.click(toggle)
  expect(screen.getByText('<b>success</b>')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Artifacts' }))
  await screen.findByRole('button', { name: 'stage/' })
  expect(screen.queryByText('<b>success</b>')).toBeNull()
})

it.each([
  ['https://mlflow.example/ui/?lang=en#' + runRoute + '/artifacts/old/file?workspace=team',
    'https://mlflow.example/ui/?lang=en#' + runRoute + '/artifacts/stage/log%20%231%3F.txt?workspace=team'],
  ['https://mlflow.example/ui' + runRoute + '?workspace=team',
    'https://mlflow.example/ui' + runRoute + '/artifacts/stage/log%20%231%3F.txt?workspace=team'],
])('links to the selected nested file when the backend detects the preview limit for %s', async (runUrl, expected) => {
  vi.spyOn(fournosApi, 'getMlflowDirectory').mockImplementation(async (_job, path) => ({
    files: path ? [{ path: 'stage/log #1?.txt', file_size: null, is_dir: false }]
      : [{ path: 'stage', file_size: null, is_dir: true }],
    next_page_token: null,
  }))
  vi.spyOn(fournosApi, 'getMlflowPreview').mockRejectedValue(
    Object.assign(new Error('Preview too large'), { isAxiosError: true, response: { status: 413 } }),
  )
  show(runUrl)
  fireEvent.click(screen.getByRole('button', { name: 'Explore files' }))
  fireEvent.click(await screen.findByRole('button', { name: 'stage/' }))
  fireEvent.click(await screen.findByRole('button', { name: 'log #1?.txt' }))
  expect(await screen.findByRole('link', { name: 'Open this file in MLflow' })).toHaveAttribute('href', expected)
  expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
})

it('keeps the CI link when the job has no MLflow run', () => {
  const list = vi.spyOn(fournosApi, 'getMlflowDirectory')
  show('')
  expect(screen.queryByRole('button', { name: 'Explore files' })).toBeNull()
  expect(screen.queryByRole('link', { name: 'Open in MLflow' })).toBeNull()
  expect(screen.getByRole('link', { name: 'CI Artifacts' })).toBeVisible()
  expect(list).not.toHaveBeenCalled()
})

it('distinguishes an unavailable listing from an empty directory', async () => {
  vi.spyOn(fournosApi, 'getMlflowDirectory')
    .mockRejectedValueOnce(new Error('MLflow is unavailable. Try again.'))
    .mockResolvedValueOnce({ files: [], next_page_token: null })
  show()
  fireEvent.click(screen.getByRole('button', { name: 'Explore files' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('MLflow is unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText('This folder is empty.')).toBeVisible()
})
