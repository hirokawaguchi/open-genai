import { useEffect, useState } from 'react';

type BundleForm = {
  id: string;
  title: string;
  public_url?: string | null;
  visibility?: string | null;
  status: string;
};

type Bundle = {
  token: string;
  procedure_name: string;
  procedure_description?: string | null;
  notice?: { notes?: string[]; prepare?: string[]; refs?: string[] };
  forms: BundleForm[];
};

const statusLabel: Record<string, string> = {
  none: '未提出',
  draft: '下書き',
  submitted: '提出済',
  withdrawn: '取下げ',
};

const tokenFromPath = () => {
  const parts = location.pathname.split('/public/p/');
  return (parts[1] || '').replace(/\/+$/, '');
};

const withApp = (url: string, token: string) => {
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}app=${encodeURIComponent(token)}`;
};

export const GuestBundle = () => {
  const token = tokenFromPath();
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setError('リンクが正しくありません');
      return;
    }
    void (async () => {
      try {
        const res = await fetch(`/public/api/applications/${encodeURIComponent(token)}`);
        const data = (await res.json().catch(() => ({}))) as Bundle & { error?: string };
        if (!res.ok) {
          throw new Error(data.error || '申請を開けませんでした');
        }
        setBundle(data);
        document.title = data.procedure_name || '手続き';
      } catch (e) {
        setError(e instanceof Error ? e.message : '申請を開けませんでした');
      }
    })();
  }, [token]);

  if (error) {
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
        <h2 className='text-std-16B-150'>必要な様式</h2>
        {bundle.forms.length === 0 ? (
          <p className='mt-2 text-solid-gray-700'>この回答では提出する様式はありません。</p>
        ) : (
          <ul className='mt-3 divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
            {bundle.forms.map((f) => {
              const guestOk = f.visibility !== 'internal' && f.public_url;
              return (
                <li key={f.id} className='py-3'>
                  {guestOk ? (
                    <a
                      href={withApp(f.public_url || '', bundle.token)}
                      className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                    >
                      {f.title}
                    </a>
                  ) : (
                    <span className='text-std-16B-150'>{f.title}</span>
                  )}
                  <p className='text-solid-gray-700'>
                    {statusLabel[f.status] || f.status}
                    {!guestOk ? ' / 庁内のみ' : ''}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </>
  );
};
