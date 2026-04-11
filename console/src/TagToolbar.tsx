import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { addTags } from './api';
import { useConsoleStore } from './store';

export function TagToolbar() {
  const [tagInput, setTagInput] = useState('');
  const selectedIds = useConsoleStore((s) => s.selectedAssetIds);
  const clearSelection = useConsoleStore((s) => s.clearSelection);
  const queryClient = useQueryClient();

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

  if (selectedIds.size === 0) return null;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && tagInput.trim()) {
      mutation.mutate(tagInput.trim());
    }
  };

  return (
    <div className="flex items-center gap-3 rounded bg-gray-800 px-4 py-2 text-sm">
      <span className="text-gray-400">
        {selectedIds.size} asset{selectedIds.size > 1 ? 's' : ''} selected
      </span>
      <input
        type="text"
        value={tagInput}
        onChange={(e) => setTagInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type tag + Enter"
        disabled={mutation.isPending}
        className="rounded border border-gray-600 bg-gray-900 px-3 py-1 text-gray-100 placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
      />
      {mutation.isPending && <span className="text-gray-500">Saving...</span>}
      {mutation.isError && <span className="text-red-400">Failed to tag</span>}
    </div>
  );
}
