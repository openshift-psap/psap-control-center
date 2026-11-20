import { Fragment, useId, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { ArrowTopRightOnSquareIcon, DocumentTextIcon, FolderIcon, ChevronDownIcon, ChevronRightIcon } from '@heroicons/react/24/outline'
import { fournosApi } from '../services/api'
import type { MlflowArtifact } from '../types'

const action = 'inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50'
const linkStyle = 'text-sm font-medium text-indigo-600 hover:underline'
const previewLimit = 64 * 1024

interface Props {
  job: string
  runUrl?: string
  ciUrl?: string
}

function webLink(value?: string) {
  if (!value) return
  try {
    const url = new URL(value)
    if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) return url.href
  } catch { /* Ignore malformed links in historical records. */ }
}

export default function JobResultLinks({ job, runUrl: recordedRun, ciUrl: recordedCi }: Props) {
  const runUrl = webLink(recordedRun)
  const ciUrl = webLink(recordedCi)
  const panel = useId()
  const [open, setOpen] = useState(false)
  const [folder, setFolder] = useState('')
  const [file, setFile] = useState<MlflowArtifact | null>(null)
  const enabled = Boolean(open && runUrl)
  const key = ['mlflow-artifacts', job, runUrl]
  const directory = useInfiniteQuery({
    queryKey: [...key, 'folder', folder],
    queryFn: ({ pageParam, signal }) => fournosApi.getMlflowDirectory(job, folder, pageParam, signal),
    enabled, initialPageParam: '',
    getNextPageParam: (page, _pages, _param, params) =>
      page.next_page_token && !params.includes(page.next_page_token) ? page.next_page_token : undefined,
    staleTime: 30_000, gcTime: 0, retry: false, refetchOnWindowFocus: false,
  })
  const tooLarge = (file?.file_size ?? 0) > previewLimit
  const preview = useQuery({
    queryKey: [...key, 'file', file?.path],
    queryFn: ({ signal }) => fournosApi.getMlflowPreview(job, file!.path, signal),
    enabled: enabled && Boolean(file) && !tooLarge,
    staleTime: 30_000, gcTime: 0, retry: false, refetchOnWindowFocus: false,
  })
  const entries = (directory.data?.pages.flatMap(page => page.files) ?? [])
    .sort((a, b) => Number(b.is_dir) - Number(a.is_dir) || a.path.localeCompare(b.path))
  const parts = folder ? folder.split('/') : []
  function browse(path: string) {
    setFolder(path)
    setFile(null)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2" aria-label="Job results">
        {runUrl && (
          <button type="button" className={action} aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)}>
            {open ? <ChevronDownIcon className="h-4 w-4" /> : <ChevronRightIcon className="h-4 w-4" />} Explore files
          </button>
        )}
        {runUrl && <a href={runUrl} target="_blank" rel="noopener noreferrer" className={action}>
          Open in MLflow <ArrowTopRightOnSquareIcon className="h-4 w-4" />
        </a>}
        {ciUrl && <a href={ciUrl} target="_blank" rel="noopener noreferrer" className={action}>
          <FolderIcon className="h-4 w-4" /> CI Artifacts
        </a>}
      </div>
      {enabled && (
        <section id={panel} aria-label="MLflow artifacts" className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <nav aria-label="Artifact folder" className="flex flex-wrap items-center gap-2 border-b border-gray-200 px-4 py-3">
            <button className={linkStyle} onClick={() => browse('')} aria-current={folder ? undefined : 'location'}>Artifacts</button>
            {parts.map((part, index) => <Fragment key={index}>
              <span aria-hidden="true" className="text-gray-400">/</span>
              <button className={linkStyle + ' break-all'} onClick={() => browse(parts.slice(0, index + 1).join('/'))}
                aria-current={index === parts.length - 1 ? 'location' : undefined}>{part}</button>
            </Fragment>)}
          </nav>
          <div className="grid md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <div aria-label="Folder contents" className="max-h-96 overflow-auto p-2">
              {directory.isPending && <p className="p-2 text-sm text-gray-500" role="status">Loading folder…</p>}
              {directory.isSuccess && !entries.length && <p className="p-2 text-sm text-gray-500">This folder is empty.</p>}
              {entries.map(entry => (
                <button key={entry.path} type="button" aria-pressed={entry.is_dir ? undefined : file?.path === entry.path}
                  className={`flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-gray-50 ${file?.path === entry.path ? 'bg-indigo-50 text-indigo-700' : 'text-gray-700'}`}
                  onClick={() => entry.is_dir ? browse(entry.path) : setFile(entry)}>
                  {entry.is_dir ? <FolderIcon className="h-4 w-4 shrink-0 text-indigo-500" /> : <DocumentTextIcon className="h-4 w-4 shrink-0" />}
                  <span className="break-all">{entry.path.split('/').pop()}{entry.is_dir ? '/' : ''}</span>
                </button>
              ))}
              {directory.isError && <p role="alert" className="p-2 text-sm text-red-700">{directory.error.message}{' '}
                <button className={linkStyle} onClick={() => void (directory.isFetchNextPageError ? directory.fetchNextPage() : directory.refetch())}>Retry</button>
              </p>}
              {directory.hasNextPage && !directory.isFetchNextPageError && <button className={linkStyle + ' p-2'} disabled={directory.isFetchingNextPage}
                onClick={() => void directory.fetchNextPage()}>{directory.isFetchingNextPage ? 'Loading…' : 'Load more'}</button>}
            </div>
            <div aria-live="polite" aria-label="File preview" className="min-w-0 border-t border-gray-200 p-4 text-sm text-gray-600 md:border-l md:border-t-0">
              {file ? <>
                <p className="break-all font-semibold text-gray-900">{file.path.split('/').pop()}</p>
                {file.file_size != null && <p className="mb-2 text-xs text-gray-500">{file.file_size.toLocaleString()} bytes</p>}
                {tooLarge ? <p>This file exceeds the 64 KiB preview limit. Open it in MLflow.</p>
                  : preview.isPending ? <p>Loading preview…</p>
                  : preview.isError ? <p role="alert">{preview.error.message}{' '}<button className={linkStyle} onClick={() => void preview.refetch()}>Retry</button></p>
                  : preview.data.text ? <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 font-mono text-xs">{preview.data.text}</pre>
                  : <p>This file is empty.</p>}
              </> : <p>Select a file to preview its contents.</p>}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
