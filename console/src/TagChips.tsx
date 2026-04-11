interface TagChipsProps {
  tags: string[];
  onRemove?: (tag: string) => void;
}

export function TagChips({ tags, onRemove }: TagChipsProps) {
  if (!tags.length) return <span className="text-gray-600">--</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <span
          key={tag}
          className="group inline-flex items-center gap-0.5 rounded bg-indigo-900/50 px-2 py-0.5 text-xs text-indigo-300"
        >
          {tag}
          {onRemove && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRemove(tag);
              }}
              className="ml-0.5 hidden text-indigo-400 hover:text-indigo-200 group-hover:inline"
              title={`Remove ${tag}`}
            >
              &times;
            </button>
          )}
        </span>
      ))}
    </div>
  );
}
