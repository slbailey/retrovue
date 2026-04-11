import { useState, useRef, useEffect, useCallback } from 'react';
import { useConsoleStore, type FilterEntry } from './store';

const COLUMNS = [
  { field: 'name', label: 'Name' },
  { field: 'state', label: 'State' },
  { field: 'approved_for_broadcast', label: 'Approved' },
  { field: 'duration_ms', label: 'Duration' },
  { field: 'tags', label: 'Tags' },
];

function Popover({
  open,
  onClose,
  anchorRef,
  children,
}: {
  open: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLElement | null>;
  children: React.ReactNode;
}) {
  const popRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        popRef.current &&
        !popRef.current.contains(e.target as Node) &&
        anchorRef.current &&
        !anchorRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose, anchorRef]);

  if (!open) return null;
  return (
    <div
      ref={popRef}
      className="absolute left-0 top-full z-50 mt-1 min-w-[260px] rounded-lg border border-gray-700 bg-gray-800 p-3 shadow-xl"
    >
      {children}
    </div>
  );
}

function FilterPanel() {
  const filters = useConsoleStore((s) => s.filters);
  const addFilter = useConsoleStore((s) => s.addFilter);
  const removeFilter = useConsoleStore((s) => s.removeFilter);
  const updateFilter = useConsoleStore((s) => s.updateFilter);

  return (
    <div className="flex flex-col gap-2">
      {filters.map((f, i) => (
        <div key={i} className="flex items-center gap-2 text-sm">
          <select
            value={f.field}
            onChange={(e) => updateFilter(i, { ...f, field: e.target.value })}
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          >
            {COLUMNS.map((c) => (
              <option key={c.field} value={c.field}>
                {c.label}
              </option>
            ))}
          </select>
          <select
            value={f.op}
            onChange={(e) =>
              updateFilter(i, {
                ...f,
                op: e.target.value as FilterEntry['op'],
              })
            }
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          >
            <option value="contains">contains</option>
            <option value="equals">equals</option>
            <option value="is">is</option>
            <option value="is_not">is not</option>
          </select>
          <input
            type="text"
            value={f.value}
            onChange={(e) => updateFilter(i, { ...f, value: e.target.value })}
            placeholder="Value..."
            className="flex-1 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200 placeholder-gray-500"
          />
          <button
            onClick={() => removeFilter(i)}
            className="text-gray-500 hover:text-gray-300"
            title="Remove filter"
          >
            &times;
          </button>
        </div>
      ))}
      <button
        onClick={() =>
          addFilter({ field: 'name', op: 'contains', value: '' })
        }
        className="self-start text-sm text-indigo-400 hover:text-indigo-300"
      >
        + Add filter
      </button>
    </div>
  );
}

function SortPanel() {
  const sorts = useConsoleStore((s) => s.sorts);
  const addSort = useConsoleStore((s) => s.addSort);
  const removeSort = useConsoleStore((s) => s.removeSort);
  const updateSort = useConsoleStore((s) => s.updateSort);

  const availableFields = COLUMNS.filter(
    (c) => !sorts.some((s) => s.field === c.field),
  );

  return (
    <div className="flex flex-col gap-2">
      {sorts.map((s) => (
        <div key={s.field} className="flex items-center gap-2 text-sm">
          <span className="text-gray-300">
            {COLUMNS.find((c) => c.field === s.field)?.label ?? s.field}
          </span>
          <button
            onClick={() =>
              updateSort(s.field, s.dir === 'asc' ? 'desc' : 'asc')
            }
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-300 hover:bg-gray-700"
          >
            {s.dir === 'asc' ? 'A → Z' : 'Z → A'}
          </button>
          <button
            onClick={() => removeSort(s.field)}
            className="text-gray-500 hover:text-gray-300"
            title="Remove sort"
          >
            &times;
          </button>
        </div>
      ))}
      {availableFields.length > 0 && (
        <button
          onClick={() => addSort(availableFields[0].field)}
          className="self-start text-sm text-indigo-400 hover:text-indigo-300"
        >
          + Add sort
        </button>
      )}
    </div>
  );
}

function GroupPanel() {
  const groupBy = useConsoleStore((s) => s.groupBy);
  const setGroupBy = useConsoleStore((s) => s.setGroupBy);

  const groupableFields = [
    { field: 'state', label: 'State' },
    { field: 'approved_for_broadcast', label: 'Approved' },
    { field: 'tags', label: 'Tags' },
  ];

  return (
    <div className="flex flex-col gap-2">
      {groupableFields.map((f) => (
        <button
          key={f.field}
          onClick={() =>
            setGroupBy(groupBy === f.field ? null : f.field)
          }
          className={`rounded px-3 py-1.5 text-left text-sm ${
            groupBy === f.field
              ? 'bg-indigo-600 text-white'
              : 'text-gray-300 hover:bg-gray-700'
          }`}
        >
          {f.label}
          {groupBy === f.field && ' ✓'}
        </button>
      ))}
      {groupBy && (
        <button
          onClick={() => setGroupBy(null)}
          className="self-start text-sm text-gray-500 hover:text-gray-300"
        >
          Remove grouping
        </button>
      )}
    </div>
  );
}

function ColumnsPanel() {
  const hiddenColumns = useConsoleStore((s) => s.hiddenColumns);
  const toggleColumn = useConsoleStore((s) => s.toggleColumn);

  return (
    <div className="flex flex-col gap-1">
      {COLUMNS.map((c) => (
        <label
          key={c.field}
          className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm text-gray-300 hover:bg-gray-700"
        >
          <input
            type="checkbox"
            checked={!hiddenColumns.has(c.field)}
            onChange={() => toggleColumn(c.field)}
            className="accent-indigo-500"
          />
          {c.label}
        </label>
      ))}
    </div>
  );
}

function ToolbarButton({
  label,
  panel,
  badge,
}: {
  label: string;
  panel: React.ReactNode;
  badge?: number;
}) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);

  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1 rounded px-2.5 py-1 text-sm ${
          open
            ? 'bg-gray-700 text-white'
            : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
        }`}
      >
        {label}
        {badge !== undefined && badge > 0 && (
          <span className="ml-1 rounded-full bg-indigo-600 px-1.5 py-0.5 text-xs text-white">
            {badge}
          </span>
        )}
      </button>
      <Popover open={open} onClose={close} anchorRef={btnRef}>
        {panel}
      </Popover>
    </div>
  );
}

export function ViewToolbar() {
  const filterCount = useConsoleStore((s) => s.filters.length);
  const sortCount = useConsoleStore((s) => s.sorts.length);
  const groupBy = useConsoleStore((s) => s.groupBy);

  return (
    <div className="flex items-center gap-1 border-b border-gray-800 px-1 py-1">
      <ToolbarButton
        label="Filter"
        panel={<FilterPanel />}
        badge={filterCount}
      />
      <ToolbarButton label="Sort" panel={<SortPanel />} badge={sortCount} />
      <ToolbarButton
        label="Group"
        panel={<GroupPanel />}
        badge={groupBy ? 1 : 0}
      />
      <ToolbarButton label="Columns" panel={<ColumnsPanel />} />
    </div>
  );
}
