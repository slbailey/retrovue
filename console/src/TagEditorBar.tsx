import { useState, useMemo, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { addTags, removeTag, fetchAllTags, type Asset } from './api';
import { useConsoleStore } from './store';

interface TagEditorBarProps {
  assets: Asset[];
}

export function TagEditorBar({ assets }: TagEditorBarProps) {
  const selectedIds = useConsoleStore((s) => s.selectedAssetIds);
  const clearSelection = useConsoleStore((s) => s.clearSelection);
  const queryClient = useQueryClient();
  const [input, setInput] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const { data: allTags = [] } = useQuery({
    queryKey: ['allTags'],
    queryFn: fetchAllTags,
  });

  // Tags shared by ALL selected assets
  const sharedTags = useMemo(() => {
    const selected = assets.filter((a) => selectedIds.has(a.uuid));
    if (selected.length === 0) return [];
    const tagSets = selected.map((a) => new Set(a.tags));
    const first = tagSets[0];
    return [...first].filter((tag) => tagSets.every((s) => s.has(tag))).sort();
  }, [assets, selectedIds]);

  const addMutation = useMutation({
    mutationFn: async (tag: string) => {
      await Promise.all(
        Array.from(selectedIds).map((id) => addTags(id, [tag])),
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets'] });
      queryClient.invalidateQueries({ queryKey: ['allTags'] });
      setInput('');
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (tag: string) => {
      await Promise.all(
        Array.from(selectedIds).map((id) => removeTag(id, tag)),
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets'] });
      queryClient.invalidateQueries({ queryKey: ['allTags'] });
    },
  });

  const suggestions = useMemo(() => {
    if (!input.trim()) return [];
    const lower = input.toLowerCase();
    return allTags
      .filter(
        (t) =>
          t.toLowerCase().includes(lower) && !sharedTags.includes(t),
      )
      .slice(0, 6);
  }, [input, allTags, sharedTags]);

  if (selectedIds.size === 0) return null;

  const isPending = addMutation.isPending || removeMutation.isPending;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-gray-700 bg-gray-850 px-4 py-2.5">
      <span className="shrink-0 text-sm font-medium text-gray-300">
        {selectedIds.size} selected
      </span>

      <div className="mx-2 h-5 w-px bg-gray-700" />

      <span className="shrink-0 text-xs font-medium uppercase tracking-wider text-gray-500">
        Tags
      </span>

      {/* Shared tags as removable chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        {sharedTags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-md bg-gray-700 px-2.5 py-1 text-sm text-gray-100"
          >
            {tag.replace(/^tag\./, '')}
            <button
              onClick={() => removeMutation.mutate(tag)}
              disabled={isPending}
              className="ml-0.5 text-gray-400 hover:text-white"
              title={`Remove ${tag} from selected`}
            >
              &times;
            </button>
          </span>
        ))}

        {/* Inline tag input */}
        <div className="relative">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setShowSuggestions(true);
            }}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && input.trim()) {
                addMutation.mutate(input.trim());
                setShowSuggestions(false);
              }
              if (e.key === 'Escape') {
                setInput('');
                setShowSuggestions(false);
                inputRef.current?.blur();
              }
            }}
            placeholder="type to add..."
            disabled={isPending}
            className="w-36 rounded border border-transparent bg-transparent px-2 py-1 text-sm text-gray-100 placeholder-gray-500 focus:border-gray-600 focus:bg-gray-900 focus:outline-none"
          />
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute left-0 top-full z-50 mt-1 w-48 rounded-lg border border-gray-700 bg-gray-800 py-1 shadow-xl">
              {suggestions.map((tag) => (
                <button
                  key={tag}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    addMutation.mutate(tag);
                    setShowSuggestions(false);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-sm text-gray-200 hover:bg-gray-700"
                >
                  {tag.replace(/^tag\./, '')}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {isPending && (
          <span className="text-xs text-gray-500">Saving...</span>
        )}
        <button
          onClick={clearSelection}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          Clear selection
        </button>
      </div>
    </div>
  );
}
