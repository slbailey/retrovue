import { useCallback, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchAssets,
  fetchAllTags,
  addTags,
  removeTag,
  updateAsset,
  type Asset,
} from './api';
import { useConsoleStore, type FilterEntry } from './store';
import { TagChips } from './TagChips';
import { ViewToolbar } from './ViewToolbar';

function nameFromUri(uri: string): string {
  const parts = uri.split('/');
  return parts[parts.length - 1] || uri;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '--';
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function getFieldValue(asset: Asset, field: string): string {
  switch (field) {
    case 'name':
      return nameFromUri(asset.uri);
    case 'state':
      return asset.state;
    case 'approved_for_broadcast':
      return asset.approved_for_broadcast ? 'Yes' : 'No';
    case 'duration_ms':
      return formatDuration(asset.duration_ms);
    case 'tags':
      return asset.tags.join(' ');
    default:
      return '';
  }
}

function matchesFilter(asset: Asset, filter: FilterEntry): boolean {
  const val = getFieldValue(asset, filter.field).toLowerCase();
  const target = filter.value.toLowerCase();
  if (!target) return true;
  switch (filter.op) {
    case 'contains':
      return val.includes(target);
    case 'equals':
      return val === target;
    case 'is':
      return val === target;
    case 'is_not':
      return val !== target;
    default:
      return true;
  }
}

function InlineTagEditor({
  assetUuid,
  allTags,
}: {
  assetUuid: string;
  allTags: string[];
}) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (tag: string) => addTags(assetUuid, [tag]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets'] });
      setInput('');
    },
  });

  const suggestions = useMemo(() => {
    if (!input.trim()) return [];
    const lower = input.toLowerCase();
    return allTags.filter((t) => t.toLowerCase().includes(lower)).slice(0, 5);
  }, [input, allTags]);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-700 hover:text-gray-300"
      >
        +
      </button>
    );
  }

  return (
    <div className="relative">
      <input
        autoFocus
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && input.trim()) {
            mutation.mutate(input.trim());
          }
          if (e.key === 'Escape') {
            setOpen(false);
            setInput('');
          }
        }}
        onBlur={() => {
          setTimeout(() => {
            setOpen(false);
            setInput('');
          }, 150);
        }}
        placeholder="Add tag..."
        className="w-24 rounded border border-gray-600 bg-gray-900 px-2 py-0.5 text-xs text-gray-200 placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
      />
      {suggestions.length > 0 && (
        <div className="absolute left-0 top-full z-50 mt-0.5 w-40 rounded border border-gray-700 bg-gray-800 py-1 shadow-lg">
          {suggestions.map((tag) => (
            <button
              key={tag}
              onMouseDown={(e) => {
                e.preventDefault();
                mutation.mutate(tag);
              }}
              className="block w-full px-3 py-1 text-left text-xs text-gray-300 hover:bg-gray-700"
            >
              {tag}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function InlineSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  const [editing, setEditing] = useState(false);

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="rounded px-1 py-0.5 text-left text-sm hover:bg-gray-700"
      >
        {value}
      </button>
    );
  }

  return (
    <select
      autoFocus
      value={value}
      onChange={(e) => {
        onChange(e.target.value);
        setEditing(false);
      }}
      onBlur={() => setEditing(false)}
      className="rounded border border-gray-600 bg-gray-900 px-1 py-0.5 text-sm text-gray-200"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function ApprovalToggle({
  approved,
  onChange,
}: {
  approved: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!approved)}
      className={`rounded px-2 py-0.5 text-xs font-medium ${
        approved
          ? 'bg-green-900/50 text-green-400'
          : 'bg-red-900/50 text-red-400'
      } hover:opacity-80`}
    >
      {approved ? 'Yes' : 'No'}
    </button>
  );
}

interface GroupedAssets {
  key: string;
  assets: Asset[];
}

export function AssetsPage() {
  const selectedIds = useConsoleStore((s) => s.selectedAssetIds);
  const setSelection = useConsoleStore((s) => s.setSelection);
  const clearSelection = useConsoleStore((s) => s.clearSelection);
  const sorts = useConsoleStore((s) => s.sorts);
  const filters = useConsoleStore((s) => s.filters);
  const groupBy = useConsoleStore((s) => s.groupBy);
  const hiddenColumns = useConsoleStore((s) => s.hiddenColumns);

  const queryClient = useQueryClient();

  const { data: assets, isLoading, error } = useQuery({
    queryKey: ['assets'],
    queryFn: fetchAssets,
    refetchInterval: 10_000,
  });

  const { data: allTags = [] } = useQuery({
    queryKey: ['allTags'],
    queryFn: fetchAllTags,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      uuid,
      patch,
    }: {
      uuid: string;
      patch: { approved_for_broadcast?: boolean; state?: string };
    }) => updateAsset(uuid, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  });

  const removeTagMutation = useMutation({
    mutationFn: ({ uuid, tag }: { uuid: string; tag: string }) =>
      removeTag(uuid, tag),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  });

  // Filter
  const filtered = useMemo(() => {
    if (!assets) return [];
    return assets.filter((a) => filters.every((f) => matchesFilter(a, f)));
  }, [assets, filters]);

  // Sort
  const sorted = useMemo(() => {
    if (sorts.length === 0) return filtered;
    return [...filtered].sort((a, b) => {
      for (const s of sorts) {
        const va = getFieldValue(a, s.field).toLowerCase();
        const vb = getFieldValue(b, s.field).toLowerCase();
        if (va < vb) return s.dir === 'asc' ? -1 : 1;
        if (va > vb) return s.dir === 'asc' ? 1 : -1;
      }
      return 0;
    });
  }, [filtered, sorts]);

  // Group
  const groups: GroupedAssets[] = useMemo(() => {
    if (!groupBy) return [{ key: '', assets: sorted }];

    const map = new Map<string, Asset[]>();

    for (const asset of sorted) {
      if (groupBy === 'tags') {
        const tags = asset.tags.length > 0 ? asset.tags : ['(no tags)'];
        for (const tag of tags) {
          const existing = map.get(tag);
          if (existing) existing.push(asset);
          else map.set(tag, [asset]);
        }
      } else {
        const val = getFieldValue(asset, groupBy) || '(empty)';
        const existing = map.get(val);
        if (existing) existing.push(asset);
        else map.set(val, [asset]);
      }
    }

    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, assets]) => ({ key, assets }));
  }, [sorted, groupBy]);

  const isAllSelected = useMemo(() => {
    if (!sorted.length) return false;
    return sorted.every((a) => selectedIds.has(a.uuid));
  }, [sorted, selectedIds]);

  const toggleAll = useCallback(() => {
    if (isAllSelected) {
      clearSelection();
    } else {
      setSelection(sorted.map((a) => a.uuid));
    }
  }, [isAllSelected, sorted, clearSelection, setSelection]);

  const toggleOne = useCallback(
    (uuid: string) => {
      const next = new Set(selectedIds);
      if (next.has(uuid)) next.delete(uuid);
      else next.add(uuid);
      setSelection(Array.from(next));
    },
    [selectedIds, setSelection],
  );

  const columns = [
    { field: 'name', label: 'Name', flex: true },
    { field: 'state', label: 'State', width: 'w-28' },
    { field: 'approved_for_broadcast', label: 'Approved', width: 'w-24' },
    { field: 'duration_ms', label: 'Duration', width: 'w-24' },
    { field: 'tags', label: 'Tags', flex: true },
  ].filter((c) => !hiddenColumns.has(c.field));

  if (error) {
    return (
      <div className="p-8 text-red-400">
        Failed to load assets: {(error as Error).message}
      </div>
    );
  }

  const totalCount = sorted.length;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <h1 className="text-xl font-semibold text-gray-100">Assets</h1>
        <span className="text-sm text-gray-500">
          {assets
            ? `${totalCount} asset${totalCount !== 1 ? 's' : ''}`
            : ''}
        </span>
      </div>

      {/* Bulk tag toolbar */}
      {selectedIds.size > 0 && (
        <BulkTagBar selectedIds={selectedIds} />
      )}

      {/* Notion-style view toolbar */}
      <div className="px-4">
        <ViewToolbar />
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-4 pb-4">
        {isLoading ? (
          <div className="py-12 text-center text-gray-500">Loading...</div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="w-10 px-2 py-2">
                  <input
                    type="checkbox"
                    checked={isAllSelected}
                    onChange={toggleAll}
                    className="accent-indigo-500"
                  />
                </th>
                {columns.map((c) => (
                  <th
                    key={c.field}
                    className={`px-3 py-2 font-medium ${c.width ?? ''}`}
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <GroupRows
                  key={group.key}
                  group={group}
                  columns={columns}
                  selectedIds={selectedIds}
                  onToggle={toggleOne}
                  allTags={allTags}
                  showGroupHeader={!!groupBy}
                  onUpdateAsset={(uuid, patch) =>
                    updateMutation.mutate({ uuid, patch })
                  }
                  onRemoveTag={(uuid, tag) =>
                    removeTagMutation.mutate({ uuid, tag })
                  }
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function GroupRows({
  group,
  columns,
  selectedIds,
  onToggle,
  allTags,
  showGroupHeader,
  onUpdateAsset,
  onRemoveTag,
}: {
  group: GroupedAssets;
  columns: { field: string; label: string; flex?: boolean; width?: string }[];
  selectedIds: Set<string>;
  onToggle: (uuid: string) => void;
  allTags: string[];
  showGroupHeader: boolean;
  onUpdateAsset: (
    uuid: string,
    patch: { approved_for_broadcast?: boolean; state?: string },
  ) => void;
  onRemoveTag: (uuid: string, tag: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <>
      {showGroupHeader && (
        <tr className="border-b border-gray-800/50">
          <td
            colSpan={columns.length + 1}
            className="px-2 py-2"
          >
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="flex items-center gap-2 text-sm font-medium text-gray-300 hover:text-white"
            >
              <span
                className={`inline-block transform text-xs text-gray-500 transition-transform ${
                  collapsed ? '' : 'rotate-90'
                }`}
              >
                &#9654;
              </span>
              {group.key}
              <span className="text-xs font-normal text-gray-500">
                {group.assets.length}
              </span>
            </button>
          </td>
        </tr>
      )}
      {!collapsed &&
        group.assets.map((asset) => (
          <AssetRow
            key={asset.uuid}
            asset={asset}
            columns={columns}
            selected={selectedIds.has(asset.uuid)}
            onToggle={() => onToggle(asset.uuid)}
            allTags={allTags}
            onUpdateAsset={onUpdateAsset}
            onRemoveTag={onRemoveTag}
          />
        ))}
    </>
  );
}

function AssetRow({
  asset,
  columns,
  selected,
  onToggle,
  allTags,
  onUpdateAsset,
  onRemoveTag,
}: {
  asset: Asset;
  columns: { field: string; label: string; flex?: boolean; width?: string }[];
  selected: boolean;
  onToggle: () => void;
  allTags: string[];
  onUpdateAsset: (
    uuid: string,
    patch: { approved_for_broadcast?: boolean; state?: string },
  ) => void;
  onRemoveTag: (uuid: string, tag: string) => void;
}) {
  return (
    <tr
      className={`border-b border-gray-800/30 transition-colors ${
        selected ? 'bg-indigo-950/30' : 'hover:bg-gray-900/50'
      }`}
    >
      <td className="w-10 px-2 py-2">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          className="accent-indigo-500"
        />
      </td>
      {columns.map((col) => (
        <td key={col.field} className={`px-3 py-2 ${col.width ?? ''}`}>
          <CellContent
            asset={asset}
            field={col.field}
            allTags={allTags}
            onUpdateAsset={onUpdateAsset}
            onRemoveTag={onRemoveTag}
          />
        </td>
      ))}
    </tr>
  );
}

function CellContent({
  asset,
  field,
  allTags,
  onUpdateAsset,
  onRemoveTag,
}: {
  asset: Asset;
  field: string;
  allTags: string[];
  onUpdateAsset: (
    uuid: string,
    patch: { approved_for_broadcast?: boolean; state?: string },
  ) => void;
  onRemoveTag: (uuid: string, tag: string) => void;
}) {
  switch (field) {
    case 'name':
      return (
        <span className="text-gray-200" title={asset.uri}>
          {nameFromUri(asset.uri)}
        </span>
      );
    case 'state':
      return (
        <InlineSelect
          value={asset.state}
          options={['new', 'enriching', 'ready', 'retired']}
          onChange={(v) => onUpdateAsset(asset.uuid, { state: v })}
        />
      );
    case 'approved_for_broadcast':
      return (
        <ApprovalToggle
          approved={asset.approved_for_broadcast}
          onChange={(v) =>
            onUpdateAsset(asset.uuid, { approved_for_broadcast: v })
          }
        />
      );
    case 'duration_ms':
      return (
        <span className="text-gray-400">
          {formatDuration(asset.duration_ms)}
        </span>
      );
    case 'tags':
      return (
        <div className="flex items-center gap-1">
          <TagChips
            tags={asset.tags}
            onRemove={(tag) => onRemoveTag(asset.uuid, tag)}
          />
          <InlineTagEditor assetUuid={asset.uuid} allTags={allTags} />
        </div>
      );
    default:
      return null;
  }
}

function BulkTagBar({ selectedIds }: { selectedIds: Set<string> }) {
  const [tagInput, setTagInput] = useState('');
  const queryClient = useQueryClient();
  const clearSelection = useConsoleStore((s) => s.clearSelection);

  const mutation = useMutation({
    mutationFn: async (tag: string) => {
      const promises = Array.from(selectedIds).map((id) => addTags(id, [tag]));
      await Promise.all(promises);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets'] });
      setTagInput('');
      clearSelection();
    },
  });

  return (
    <div className="mx-4 flex items-center gap-3 rounded-lg bg-gray-800/80 px-4 py-2 text-sm">
      <span className="text-gray-400">
        {selectedIds.size} selected
      </span>
      <input
        type="text"
        value={tagInput}
        onChange={(e) => setTagInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && tagInput.trim()) {
            mutation.mutate(tagInput.trim());
          }
        }}
        placeholder="Tag all selected..."
        disabled={mutation.isPending}
        className="rounded border border-gray-600 bg-gray-900 px-3 py-1 text-gray-100 placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
      />
      {mutation.isPending && <span className="text-gray-500">Saving...</span>}
    </div>
  );
}
