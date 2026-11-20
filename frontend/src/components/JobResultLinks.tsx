import { useId, useState } from 'react'
import { ArrowTopRightOnSquareIcon, FolderIcon, ChevronDownIcon, ChevronRightIcon } from '@heroicons/react/24/outline'
import { webLink } from '../utils/webLink'
import MlflowArtifactExplorer from './MlflowArtifactExplorer'

const action = 'inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50'

interface Props {
  job: string
  runUrl?: string
  ciUrl?: string
}

export default function JobResultLinks({ job, runUrl: recordedRun, ciUrl: recordedCi }: Props) {
  const runUrl = webLink(recordedRun)
  const ciUrl = webLink(recordedCi)
  const panel = useId()
  const [open, setOpen] = useState(false)
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
      {runUrl && <MlflowArtifactExplorer id={panel} job={job} runUrl={runUrl} open={open} />}
    </div>
  )
}
