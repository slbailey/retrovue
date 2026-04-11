import { create } from 'zustand';

interface ConsoleState {
  selectedAssetIds: Set<string>;
  toggleSelection: (id: string) => void;
  setSelection: (ids: string[]) => void;
  clearSelection: () => void;
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
}));
