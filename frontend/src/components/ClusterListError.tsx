export default function ClusterListError({ retry }: { retry: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <span>Unable to load the cluster list.</span>
      <button type="button" onClick={retry} className="font-medium underline">Retry</button>
    </div>
  )
}
