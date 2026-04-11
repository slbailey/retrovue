interface TagChipsProps {
  tags: string[];
}

export function TagChips({ tags }: TagChipsProps) {
  if (!tags.length) return <span className="text-gray-500">--</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <span
          key={tag}
          className="inline-block rounded-md bg-gray-700 px-2 py-0.5 text-xs font-medium text-gray-100"
        >
          {tag.replace(/^tag\./, '')}
        </span>
      ))}
    </div>
  );
}
