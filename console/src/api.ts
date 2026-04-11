export interface Asset {
  uuid: string;
  container_id: string;
  uri: string;
  canonical_uri: string;
  state: string;
  approved_for_broadcast: boolean;
  duration_ms: number | null;
  tags: string[];
}

export interface AssetsPage {
  assets: Asset[];
  count: number;
  total: number;
  page: number;
  page_size: number;
}

interface TagsResponse {
  asset_uuid: string;
  tags: string[];
}

const BASE = import.meta.env.VITE_API_BASE_URL || '/api';

export async function fetchAssetsPage(page: number, pageSize: number): Promise<AssetsPage> {
  const res = await fetch(`${BASE}/assets?page=${page}&page_size=${pageSize}`);
  if (!res.ok) throw new Error(`Failed to fetch assets: ${res.status}`);
  return res.json();
}

export async function fetchAllTags(): Promise<string[]> {
  const res = await fetch(`${BASE}/tags`);
  if (!res.ok) throw new Error(`Failed to fetch tags: ${res.status}`);
  const data: { tags: string[] } = await res.json();
  return data.tags;
}

export async function addTags(assetUuid: string, tags: string[]): Promise<TagsResponse> {
  const res = await fetch(`${BASE}/assets/${assetUuid}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags }),
  });
  if (!res.ok) throw new Error(`Failed to add tags: ${res.status}`);
  return res.json();
}

export async function removeTag(assetUuid: string, tag: string): Promise<TagsResponse> {
  const res = await fetch(`${BASE}/assets/${assetUuid}/tags/${encodeURIComponent(tag)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed to remove tag: ${res.status}`);
  return res.json();
}

export async function updateAsset(
  assetUuid: string,
  patch: { approved_for_broadcast?: boolean; state?: string },
): Promise<Asset> {
  const res = await fetch(`${BASE}/assets/${assetUuid}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`Failed to update asset: ${res.status}`);
  return res.json();
}
