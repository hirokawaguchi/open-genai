import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { usePatchformApi } from '../PatchformApiContext';
import { readSession } from './guestSession';

type SlotTemplate = {
  file_id: string;
  filename: string;
  mime?: string;
  size?: number;
};

type ApplicationStatusBlock = {
  auto: string;
  override: string;
  effective: string;
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
  added_by?: string;
  public_url?: string | null;
  visibility?: string | null;
  can_fill_online: boolean;
  template?: SlotTemplate | null;
  status: string;
};

type Bundle = {
  id: string;
  token: string;
  procedure_id: string;
  procedure_name: string;
  procedure_description?: string | null;
  notice?: { notes?: string[]; prepare?: string[]; refs?: string[] };
  items: BundleItem[];
  status?: ApplicationStatusBlock;
  public_url?: string | null;
};

type CatalogSlot = {
  slot_id: string;
  title: string;
  kind: string;
  form_id?: string | null;
};

const OTHER_ATTACH_SLOT = 'attach:__other__';
const OTHER_ATTACH_LABEL = 'その他（別途ファイルを添付する場合にお使いください）';

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
  const api = usePatchformApi();
  const token = tokenFromPath();
  const fromMy = new URLSearchParams(location.search).get('from') === 'my';
  const authed = Boolean(readSession());
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [catalog, setCatalog] = useState<CatalogSlot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [catalogPick, setCatalogPick] = useState('');
  const [attachTitle, setAttachTitle] = useState('');
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const load = async () => {
    const res = await api.get<Bundle>(
      `/public/api/applications/${encodeURIComponent(token)}`,
    );
    setBundle(res.data);
    document.title = res.data.procedure_name || '手続き';
  };

  useEffect(() => {
    if (!token) {
      setError('リンクが正しくありません');
      return;
    }
    void (async () => {
      try {
        await load();
        const res = await api.get<{ slots?: CatalogSlot[] }>(
          `/public/api/applications/${encodeURIComponent(token)}/catalog`,
        );
        setCatalog(res.data.slots || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : '申請を開けませんでした');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const call = async (
    path: string,
    method: 'POST' | 'DELETE',
    body?: unknown,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const res =
        method === 'DELETE'
          ? await api.delete<Bundle>(path, body)
          : await api.post<Bundle>(path, body);
      setBundle(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作に失敗しました');
    } finally {
      setBusy(false);
    }
  };

  const onSetStatus = async (status: string) => {
    if (!bundle) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<Bundle>(
        `/public/api/applications/${encodeURIComponent(bundle.id)}/status`,
        { status },
      );
      setBundle(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : '状態の更新に失敗しました');
    } finally {
      setBusy(false);
    }
  };

  const onDuplicate = (item: BundleItem) =>
    call(`/public/api/applications/${encodeURIComponent(token)}/items`, 'POST', {
      duplicate_of: item.id,
    });

  const onRemove = (item: BundleItem) => {
    const label = item.slot_id === OTHER_ATTACH_SLOT ? OTHER_ATTACH_LABEL : item.title;
    if (!window.confirm(`「${label}」の枠を削除します。よろしいですか？`)) return;
    void call(
      `/public/api/applications/${encodeURIComponent(token)}/items/${encodeURIComponent(item.id)}`,
      'DELETE',
    );
  };

  const onAddCatalog = () => {
    if (!catalogPick) return;
    void call(`/public/api/applications/${encodeURIComponent(token)}/items`, 'POST', {
      form_id: catalogPick,
    });
    setCatalogPick('');
  };

  const onAddAttach = () => {
    if (!attachTitle.trim()) return;
    void call(`/public/api/applications/${encodeURIComponent(token)}/items`, 'POST', {
      title: attachTitle.trim(),
    });
    setAttachTitle('');
  };

  const onPickFile = async (item: BundleItem, file: File | undefined) => {
    if (!file) return;
    const data = await fileToDataUrl(file);
    await call(
      `/public/api/applications/${encodeURIComponent(token)}/items/${encodeURIComponent(item.id)}/file`,
      'POST',
      { filename: file.name, data },
    );
  };

  const onClearFile = (item: BundleItem) =>
    call(
      `/public/api/applications/${encodeURIComponent(token)}/items/${encodeURIComponent(item.id)}/file`,
      'DELETE',
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
  const effective = bundle.status?.effective || '';
  const submitted = effective === '提出済';
  const withdrawn = effective === '取下げ';
  return (
    <>
      {fromMy && authed ? (
        <p className='mb-2'>
          <a href='/public/mine' className='text-blue-900 underline-offset-2 hover:underline'>
            ← マイ手続きに戻る
          </a>
        </p>
      ) : null}
      <h1 className='text-std-20B-160'>{bundle.procedure_name}</h1>
      {bundle.procedure_description ? (
        <p className='mt-2 text-solid-gray-700'>{bundle.procedure_description}</p>
      ) : null}
      <p className='mt-2 text-solid-gray-700'>
        案内番号: <strong>{bundle.token}</strong>
      </p>
      {authed && bundle.status ? (
        <div className='mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-solid-gray-300 p-3'>
          <span className='text-dns-14N-130 text-solid-gray-700'>
            状態: <strong>{effective || '未着手'}</strong>
          </span>
          {!submitted && !withdrawn ? (
            <Button
              type='button'
              variant='solid-fill'
              size='sm'
              aria-disabled={busy}
              onClick={() => {
                if (window.confirm('この内容で提出します。よろしいですか？')) {
                  void onSetStatus('提出済');
                }
              }}
            >
              提出する
            </Button>
          ) : null}
          {submitted ? (
            <Button
              type='button'
              variant='outline'
              size='sm'
              aria-disabled={busy}
              onClick={() => void onSetStatus('取下げ')}
            >
              提出を取下げ
            </Button>
          ) : null}
          {withdrawn ? (
            <Button
              type='button'
              variant='outline'
              size='sm'
              aria-disabled={busy}
              onClick={() => void onSetStatus('')}
            >
              取下げを解除
            </Button>
          ) : null}
        </div>
      ) : null}
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
              const displayTitle = f.slot_id === OTHER_ATTACH_SLOT ? OTHER_ATTACH_LABEL : f.title;
              const removable =
                f.kind !== 'data' &&
                (f.copy_index > 0 || (!!f.added_by && f.added_by !== 'system'));
              return (
                <li key={f.id} className='py-3'>
                  <div className='flex flex-wrap items-baseline gap-2'>
                    {f.can_fill_online && guestOk && !filled ? (
                      <a
                        href={withApp(f.public_url || '', bundle.token, f.id)}
                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                      >
                        {displayTitle}
                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                      </a>
                    ) : (
                      <span className='text-std-16B-150'>
                        {displayTitle}
                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                      </span>
                    )}
                    <span className='rounded bg-solid-gray-100 px-2 py-0.5 text-dns-14N-130 text-solid-gray-700'>
                      {kindLabel[f.kind] || f.kind}
                    </span>
                  </div>
                  <p className='text-solid-gray-700'>
                    {statusLabel[f.status] || f.status}
                    {!guestOk && f.can_fill_online ? ' / 庁内のみ' : ''}
                  </p>
                  {filled && f.file_name ? (
                    <p className='mt-1'>
                      <a
                        href={`/public/api/applications/${encodeURIComponent(bundle.token)}/items/${encodeURIComponent(f.id)}/file`}
                        className='text-blue-900 underline-offset-2 hover:underline'
                      >
                        添付ファイルをダウンロード（{f.file_name}）
                      </a>
                    </p>
                  ) : null}
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
                      {removable && (
                        <button
                          type='button'
                          className='rounded border border-solid-gray-400 px-3 py-1 text-dns-14N-130 text-error-1'
                          disabled={busy}
                          onClick={() => onRemove(f)}
                        >
                          削除
                        </button>
                      )}
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
