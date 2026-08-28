import { useEffect, useRef, useState } from 'react';

type SlotTemplate = {
  file_id: string;
  filename: string;
  mime?: string;
  size?: number;
};

type BundleItem = {
  id: string;
  slot_id: string;
  title: string;
  kind: 'data' | 'yoshiki' | 'attach';
  required: string;
  cardinality: string;
  form_id?: string | null;
  fulfillment: '' | 'form' | 'file';
  file_name?: string | null;
  copy_index: number;
  public_url?: string | null;
  visibility?: string | null;
  can_fill_online: boolean;
  template?: SlotTemplate | null;
  status: string;
};

type Bundle = {
  token: string;
  procedure_id: string;
  procedure_name: string;
  procedure_description?: string | null;
  notice?: { notes?: string[]; prepare?: string[]; refs?: string[] };
  items: BundleItem[];
};

type CatalogSlot = {
  slot_id: string;
  title: string;
  kind: string;
  form_id?: string | null;
};

const statusLabel: Record<string, string> = {
  none: '未充足',
  draft: '記入中',
  submitted: '提出済',
  withdrawn: '取下げ',
};

const kindLabel: Record<string, string> = {
  data: '記入必須',
  yoshiki: '様式',
  attach: '添付',
};

const tokenFromPath = () => {
  const parts = location.pathname.split('/public/p/');
  return (parts[1] || '').replace(/\/+$/, '');
};

const withApp = (url: string, token: string, itemId: string) => {
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}app=${encodeURIComponent(token)}&item=${encodeURIComponent(itemId)}`;
};

const fileToDataUrl = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

export const GuestBundle = () => {
  const token = tokenFromPath();
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [catalog, setCatalog] = useState<CatalogSlot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [catalogPick, setCatalogPick] = useState('');
  const [attachTitle, setAttachTitle] = useState('');
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const load = async () => {
    const res = await fetch(`/public/api/applications/${encodeURIComponent(token)}`);
    const data = (await res.json().catch(() => ({}))) as Bundle & { error?: string };
    if (!res.ok) {
      throw new Error(data.error || '申請を開けませんでした');
    }
    setBundle(data);
    document.title = data.procedure_name || '手続き';
  };

  useEffect(() => {
    if (!token) {
      setError('リンクが正しくありません');
      return;
    }
    void (async () => {
      try {
        await load();
        const res = await fetch(`/public/api/applications/${encodeURIComponent(token)}/catalog`);
        const data = (await res.json().catch(() => ({}))) as { slots?: CatalogSlot[] };
        setCatalog(data.slots || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : '申請を開けませんでした');
      }
    })();
  }, [token]);

  const call = async (path: string, opts: RequestInit) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      });
      const data = (await res.json().catch(() => ({}))) as Bundle & { error?: string };
      if (!res.ok) throw new Error(data.error || '操作に失敗しました');
      setBundle(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作に失敗しました');
    } finally {
      setBusy(false);
    }
  };

  const onDuplicate = (item: BundleItem) =>
    call(`/public/api/applications/${encodeURIComponent(token)}/items`, {
      method: 'POST',
      body: JSON.stringify({ duplicate_of: item.id }),
    });

  const onAddCatalog = () => {
    if (!catalogPick) return;
    void call(`/public/api/applications/${encodeURIComponent(token)}/items`, {
      method: 'POST',
      body: JSON.stringify({ form_id: catalogPick }),
    });
    setCatalogPick('');
  };

  const onAddAttach = () => {
    if (!attachTitle.trim()) return;
    void call(`/public/api/applications/${encodeURIComponent(token)}/items`, {
      method: 'POST',
      body: JSON.stringify({ title: attachTitle.trim() }),
    });
    setAttachTitle('');
  };

  const onPickFile = async (item: BundleItem, file: File | undefined) => {
    if (!file) return;
    const data = await fileToDataUrl(file);
    await call(
      `/public/api/applications/${encodeURIComponent(token)}/items/${encodeURIComponent(item.id)}/file`,
      { method: 'POST', body: JSON.stringify({ filename: file.name, data }) },
    );
  };

  const onClearFile = (item: BundleItem) =>
    call(
      `/public/api/applications/${encodeURIComponent(token)}/items/${encodeURIComponent(item.id)}/file`,
      { method: 'DELETE' },
    );

  if (error && !bundle) {
    return (
      <p className='text-error-1' role='alert'>
        {error}
      </p>
    );
  }
  if (!bundle) {
    return <p className='hint text-solid-gray-700'>読み込み中...</p>;
  }

  const notice = bundle.notice;
  return (
    <>
      <h1 className='text-std-20B-160'>{bundle.procedure_name}</h1>
      {bundle.procedure_description ? (
        <p className='mt-2 text-solid-gray-700'>{bundle.procedure_description}</p>
      ) : null}
      <p className='mt-2 text-solid-gray-700'>
        案内番号: <strong>{bundle.token}</strong>
      </p>
      <p className='mt-1 text-solid-gray-700'>このセットで始めてください。足りなければ足せます。</p>
      {error ? (
        <p className='mt-2 text-error-1' role='alert'>
          {error}
        </p>
      ) : null}
      {(notice?.notes || []).length > 0 && (
        <section className='mt-6'>
          <h2 className='text-std-16B-150'>解説</h2>
          <ul className='mt-2 list-disc pl-5'>
            {notice?.notes?.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}
      {(notice?.prepare || []).length > 0 && (
        <section className='mt-6'>
          <h2 className='text-std-16B-150'>準備するもの</h2>
          <ul className='mt-2 list-disc pl-5'>
            {notice?.prepare?.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}
      <section className='mt-6'>
        <h2 className='text-std-16B-150'>提出書類一覧</h2>
        {bundle.items.length === 0 ? (
          <p className='mt-2 text-solid-gray-700'>この回答では推奨する枠がありません。下から足せます。</p>
        ) : (
          <ul className='mt-3 divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
            {bundle.items.map((f) => {
              const guestOk = f.visibility !== 'internal' && f.public_url;
              const filled = f.fulfillment === 'file';
              return (
                <li key={f.id} className='py-3'>
                  <div className='flex flex-wrap items-baseline gap-2'>
                    {f.can_fill_online && guestOk && !filled ? (
                      <a
                        href={withApp(f.public_url || '', bundle.token, f.id)}
                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                      >
                        {f.title}
                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                      </a>
                    ) : (
                      <span className='text-std-16B-150'>
                        {f.title}
                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                      </span>
                    )}
                    <span className='rounded bg-solid-gray-100 px-2 py-0.5 text-dns-14N-130 text-solid-gray-700'>
                      {kindLabel[f.kind] || f.kind}
                    </span>
                  </div>
                  <p className='text-solid-gray-700'>
                    {statusLabel[f.status] || f.status}
                    {filled && f.file_name ? ` / 添付: ${f.file_name}` : ''}
                    {!guestOk && f.can_fill_online ? ' / 庁内のみ' : ''}
                  </p>
                  {f.template ? (
                    <p className='mt-1'>
                      <a
                        href={`/public/api/applications/${encodeURIComponent(bundle.token)}/items/${encodeURIComponent(f.id)}/template`}
                        className='text-blue-900 underline-offset-2 hover:underline'
                      >
                        様式ひな型をダウンロード（{f.template.filename}）
                      </a>
                    </p>
                  ) : null}
                  {f.kind !== 'data' && (
                    <div className='mt-2 flex flex-wrap gap-2'>
                      {filled ? (
                        <button
                          type='button'
                          className='rounded border border-solid-gray-400 px-3 py-1 text-dns-14N-130'
                          disabled={busy}
                          onClick={() => void onClearFile(f)}
                        >
                          添付を取り消す
                        </button>
                      ) : (
                        <>
                          <input
                            ref={(el) => {
                              fileInputs.current[f.id] = el;
                            }}
                            type='file'
                            className='hidden'
                            onChange={(e) => void onPickFile(f, e.target.files?.[0])}
                          />
                          <button
                            type='button'
                            className='rounded border border-solid-gray-400 px-3 py-1 text-dns-14N-130'
                            disabled={busy}
                            onClick={() => fileInputs.current[f.id]?.click()}
                          >
                            記入済みファイルを添付する
                          </button>
                        </>
                      )}
                      <button
                        type='button'
                        className='rounded border border-solid-gray-400 px-3 py-1 text-dns-14N-130'
                        disabled={busy}
                        onClick={() => void onDuplicate(f)}
                      >
                        同じ枠をもう1件
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <section className='mt-6 flex flex-col gap-3 rounded-lg border border-solid-gray-300 p-4'>
        <h2 className='text-std-16B-150'>枠を足す</h2>
        {catalog.filter((s) => s.form_id).length > 0 && (
          <div className='flex flex-wrap items-center gap-2'>
            <label htmlFor='guest-catalog'>別の様式を足す</label>
            <select
              id='guest-catalog'
              className='rounded border border-solid-gray-400 px-2 py-1'
              value={catalogPick}
              onChange={(e) => setCatalogPick(e.target.value)}
            >
              <option value=''>選択してください</option>
              {catalog
                .filter((s) => s.form_id)
                .map((s) => (
                  <option key={s.slot_id} value={s.form_id ?? ''}>
                    {s.title}
                  </option>
                ))}
            </select>
            <button
              type='button'
              className='rounded border border-solid-gray-400 px-3 py-1'
              disabled={busy || !catalogPick}
              onClick={onAddCatalog}
            >
              足す
            </button>
          </div>
        )}
        <div className='flex flex-wrap items-center gap-2'>
          <label htmlFor='guest-attach'>添付を足す</label>
          <input
            id='guest-attach'
            className='rounded border border-solid-gray-400 px-2 py-1'
            placeholder='例: 住民票の写し'
            value={attachTitle}
            onChange={(e) => setAttachTitle(e.target.value)}
          />
          <button
            type='button'
            className='rounded border border-solid-gray-400 px-3 py-1'
            disabled={busy || !attachTitle.trim()}
            onClick={onAddAttach}
          >
            足す
          </button>
        </div>
      </section>
    </>
  );
};
