import { useCallback, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AgGridReact } from 'ag-grid-react';
import {
  AllCommunityModule,
  ModuleRegistry,
  type ColDef,
  type SelectionChangedEvent,
  type ICellRendererParams,
} from 'ag-grid-community';
import { fetchAssetsPage, type Asset } from './api';
import { useConsoleStore } from './store';
import { TagChips } from './TagChips';
import { TagEditorBar } from './TagEditorBar';

ModuleRegistry.registerModules([AllCommunityModule]);

const PAGE_SIZE = 200;

/**
 * Fetch all asset pages sequentially. Server-driven pagination ensures
 * we never hard-cap the dataset. Fetches PAGE_SIZE at a time until all
 * assets are loaded.
 */
async function fetchAllAssets(): Promise<Asset[]> {
  const all: Asset[] = [];
  let page = 1;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const result = await fetchAssetsPage(page, PAGE_SIZE);
    all.push(...result.assets);
    if (all.length >= result.total || result.assets.length < PAGE_SIZE) {
      break;
    }
    page++;
  }

  return all;
}

function TagCellRenderer(params: ICellRendererParams<Asset>) {
  return <TagChips tags={params.value ?? []} />;
}

function nameFromUri(uri: string): string {
  const parts = uri.split('/');
  return parts[parts.length - 1] || uri;
}

export function AssetsPage() {
  const gridRef = useRef<AgGridReact<Asset>>(null);
  const setSelection = useConsoleStore((s) => s.setSelection);
  const [tagFilter, setTagFilter] = useState('');

  const { data: assets, isLoading, error } = useQuery({
    queryKey: ['assets'],
    queryFn: fetchAllAssets,
    refetchInterval: 30_000,
  });

  const filteredAssets = useMemo(() => {
    if (!assets) return [];
    if (!tagFilter.trim()) return assets;
    const filter = tagFilter.trim().toLowerCase();
    return assets.filter((a) =>
      a.tags.some((t) => t.toLowerCase().includes(filter)),
    );
  }, [assets, tagFilter]);

  const columnDefs = useMemo<ColDef<Asset>[]>(
    () => [
      {
        headerCheckboxSelection: true,
        checkboxSelection: true,
        width: 50,
        sortable: false,
        filter: false,
        resizable: false,
      },
      {
        headerName: 'Name',
        valueGetter: (p) => (p.data ? nameFromUri(p.data.uri) : ''),
        flex: 2,
        filter: true,
        sortable: true,
      },
      {
        headerName: 'State',
        field: 'state',
        width: 120,
        filter: true,
        sortable: true,
      },
      {
        headerName: 'Approved',
        field: 'approved_for_broadcast',
        width: 120,
        valueFormatter: (p) => (p.value ? 'Yes' : 'No'),
        filter: true,
        sortable: true,
      },
      {
        headerName: 'Tags',
        field: 'tags',
        flex: 2,
        cellRenderer: TagCellRenderer,
        filter: true,
        filterValueGetter: (p) => (p.data?.tags ?? []).join(' '),
        autoHeight: true,
      },
    ],
    [],
  );

  const onSelectionChanged = useCallback(
    (event: SelectionChangedEvent<Asset>) => {
      const selected = event.api.getSelectedRows();
      setSelection(selected.map((a) => a.uuid));
    },
    [setSelection],
  );

  if (error) {
    return (
      <div className="p-8 text-base text-red-400">
        Failed to load assets: {(error as Error).message}
      </div>
    );
  }

  const totalLoaded = assets?.length ?? 0;
  const displayCount = filteredAssets.length;

  return (
    <div className="flex h-full flex-col gap-3 p-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-100">Assets</h1>
        <span className="text-sm text-gray-500">
          {isLoading
            ? 'Loading...'
            : tagFilter
              ? `${displayCount} of ${totalLoaded} assets`
              : `${totalLoaded} assets`}
        </span>
      </div>

      {/* Tag Editor Bar — appears when assets selected */}
      <TagEditorBar assets={filteredAssets} />

      {/* Tag filter */}
      <div className="flex items-center gap-3 text-sm">
        <label className="text-gray-400">Filter by tag:</label>
        <input
          type="text"
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          placeholder="Type to filter..."
          className="rounded-md border border-gray-600 bg-gray-900 px-3 py-1.5 text-sm text-gray-100 placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
        />
        {tagFilter && (
          <button
            onClick={() => setTagFilter('')}
            className="text-sm text-gray-500 underline hover:text-gray-300"
          >
            Clear
          </button>
        )}
      </div>

      {/* Grid */}
      <div className="ag-theme-alpine-dark flex-1" style={{ minHeight: 500 }}>
        <AgGridReact<Asset>
          ref={gridRef}
          rowData={filteredAssets}
          columnDefs={columnDefs}
          getRowId={(params) => params.data.uuid}
          rowSelection="multiple"
          onSelectionChanged={onSelectionChanged}
          loading={isLoading}
          domLayout="normal"
          rowHeight={42}
          headerHeight={40}
        />
      </div>
    </div>
  );
}
