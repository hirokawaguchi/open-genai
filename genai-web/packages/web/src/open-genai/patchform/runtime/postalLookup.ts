type PostalResult = { prefecture?: string; city?: string; street?: string };

/** 庁内プロキシが未配備でも使えるよう、zipcloud を直接引く。 */
export const lookupPostalDirect = async (zip: string): Promise<PostalResult | null> => {
  const zipD = (zip || '').replace(/\D/g, '');
  if (zipD.length !== 7) {
    throw new Error('郵便番号は7桁です');
  }
  const res = await fetch(`https://zipcloud.ibsnet.co.jp/api/search?zipcode=${zipD}`);
  if (!res.ok) {
    throw new Error('住所の検索に失敗しました');
  }
  const data = (await res.json()) as {
    status?: number;
    results?: Array<{ address1?: string; address2?: string; address3?: string }>;
  };
  const first = data.status === 200 ? data.results?.[0] : undefined;
  if (!first) return null;
  return {
    prefecture: first.address1 || '',
    city: first.address2 || '',
    street: first.address3 || '',
  };
};
