import { create } from 'zustand';

export type SortDir = 'asc' | 'desc';
export interface SortEntry {
  field: string;
  dir: SortDir;
}

export interface FilterEntry {
  field: string;
  op: 'contains' | 'equals' | 'is' | 'is_not';
  value: string;
}

export interface ConsoleState {
  // Selection
  selectedAssetIds: Set<string>;
  toggleSelection: (id: string) => void;
  setSelection: (ids: string[]) => void;
  clearSelection: () => void;

  // Sorts
  sorts: SortEntry[];
  addSort: (field: string) => void;
  removeSort: (field: string) => void;
  updateSort: (field: string, dir: SortDir) => void;

  // Filters
  filters: FilterEntry[];
  addFilter: (filter: FilterEntry) => void;
  removeFilter: (index: number) => void;
  updateFilter: (index: number, filter: FilterEntry) => void;

  // Grouping
  groupBy: string | null;
  setGroupBy: (field: string | null) => void;

  // Column visibility
  hiddenColumns: Set<string>;
  toggleColumn: (field: string) => void;
}

export const useConsoleStore = create<ConsoleState>((set) => ({
  selectedAssetIds: new Set(),
  toggleSelection: (id) =>
    set((state) => {
      const next = new Set(state.selectedAssetIds);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { selectedAssetIds: next };
    }),
  setSelection: (ids) => set({ selectedAssetIds: new Set(ids) }),
  clearSelection: () => set({ selectedAssetIds: new Set() }),

  sorts: [],
  addSort: (field) =>
    set((state) => {
      if (state.sorts.some((s) => s.field === field)) return state;
      return { sorts: [...state.sorts, { field, dir: 'asc' as SortDir }] };
    }),
  removeSort: (field) =>
    set((state) => ({
      sorts: state.sorts.filter((s) => s.field !== field),
    })),
  updateSort: (field, dir) =>
    set((state) => ({
      sorts: state.sorts.map((s) => (s.field === field ? { ...s, dir } : s)),
    })),

  filters: [],
  addFilter: (filter) =>
    set((state) => ({ filters: [...state.filters, filter] })),
  removeFilter: (index) =>
    set((state) => ({
      filters: state.filters.filter((_, i) => i !== index),
    })),
  updateFilter: (index, filter) =>
    set((state) => ({
      filters: state.filters.map((f, i) => (i === index ? filter : f)),
    })),

  groupBy: null,
  setGroupBy: (field) => set({ groupBy: field }),

  hiddenColumns: new Set(),
  toggleColumn: (field) =>
    set((state) => {
      const next = new Set(state.hiddenColumns);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return { hiddenColumns: next };
    }),
}));
