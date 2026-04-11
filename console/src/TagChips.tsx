interface TagChipsProps {
  tags: string[];
}

export function TagChips({ tags }: TagChipsProps) {
  if (!tags.length) return <span className="text-gray-600">--</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <span
          key={tag}
          className="inline-block rounded bg-indigo-900/50 px-2 py-0.5 text-xs text-indigo-300"
        >
          {tag}
        </span>
      ))}
    </div>
  );
}
