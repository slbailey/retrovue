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

interface AssetsResponse {
  assets: Asset[];
  count: number;
}

interface TagsResponse {
  asset_uuid: string;
  tags: string[];
}

const BASE = '/api/console';

export async function fetchAssets(): Promise<Asset[]> {
  const res = await fetch(`${BASE}/assets`);
  if (!res.ok) throw new Error(`Failed to fetch assets: ${res.status}`);
  const data: AssetsResponse = await res.json();
  return data.assets;
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
