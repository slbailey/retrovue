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
import { fetchAssets, type Asset } from './api';
import { useConsoleStore } from './store';
import { TagChips } from './TagChips';
import { TagToolbar } from './TagToolbar';

ModuleRegistry.registerModules([AllCommunityModule]);

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
    queryFn: fetchAssets,
    refetchInterval: 10_000,
  });

  const filteredAssets = useMemo(() => {
    if (!assets) return [];
    if (!tagFilter.trim()) return assets;
    const filter = tagFilter.trim().toLowerCase();
    return assets.filter((a) =>
      a.tags.some((t) => t.toLowerCase().includes(filter))
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
        width: 110,
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
      <div className="p-8 text-red-400">
        Failed to load assets: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-100">Assets</h1>
        <span className="text-sm text-gray-500">
          {assets ? `${filteredAssets.length} asset${filteredAssets.length !== 1 ? 's' : ''}` : ''}
        </span>
      </div>

      <TagToolbar />

      <div className="flex items-center gap-3 text-sm">
        <label className="text-gray-400">Filter by tag:</label>
        <input
          type="text"
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          placeholder="Type to filter..."
          className="rounded border border-gray-600 bg-gray-900 px-3 py-1 text-gray-100 placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
        />
        {tagFilter && (
          <button
            onClick={() => setTagFilter('')}
            className="text-xs text-gray-500 hover:text-gray-300 underline"
          >
            Clear
          </button>
        )}
      </div>

      <div className="ag-theme-alpine-dark flex-1" style={{ minHeight: 400 }}>
        <AgGridReact<Asset>
          ref={gridRef}
          rowData={filteredAssets}
          columnDefs={columnDefs}
          getRowId={(params) => params.data.uuid}
          rowSelection="multiple"
          onSelectionChanged={onSelectionChanged}
          loading={isLoading}
          domLayout="autoHeight"
        />
      </div>
    </div>
  );
}
