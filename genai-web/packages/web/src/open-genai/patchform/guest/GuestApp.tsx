import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { FillForm } from '../runtime/FillForm';
import { answerRows } from '../runtime/formatAnswer';
import { lookupPostalDirect } from '../runtime/postalLookup';
import { missingRequired } from '../runtime/visibility';
import type { FormDefinition, UploadedFile } from '../types';

type PublicForm = {
  title?: string;
  description?: string | null;
  requires_pin?: boolean;
  allow_draft?: boolean;
  allow_multiple?: boolean;
  identity_mode?: 'required' | 'optional' | 'anonymous';
  has_name_composite?: boolean;
  definition?: FormDefinition;
};

type GuestState = { resume?: string; receipt?: string; submitted?: boolean };

const storageKey = (token: string) => `patchform-guest:${token}`;

const readGuestState = (token: string): GuestState => {
  try {
    return JSON.parse(localStorage.getItem(storageKey(token)) || '{}') as GuestState;
  } catch {
    return {};
  }
};

const writeGuestState = (token: string, patch: GuestState) => {
  localStorage.setItem(storageKey(token), JSON.stringify({ ...readGuestState(token), ...patch }));
};

const tokenFromPath = () => {
  const parts = location.pathname.split('/public/f/');
  return (parts[1] || '').replace(/\/+$/, '');
};

const fileToDataUrl = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

const api = async <T,>(path: string, opts?: RequestInit): Promise<T> => {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || '通信に失敗しました');
  }
  return data;
};

export const GuestApp = () => {
  const token = tokenFromPath();
  const [phase, setPhase] = useState<
    'load' | 'pin' | 'form' | 'confirm' | 'done' | 'withdrawn' | 'error'
  >('load');
  const [pin, setPin] = useState('');
  const [form, setForm] = useState<PublicForm | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [submitterName, setSubmitterName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState('');
  const [busy, setBusy] = useState(false);
  const [wizardLast, setWizardLast] = useState(true);
  const [draftNote, setDraftNote] = useState<string | null>(null);
  const [resumeToken, setResumeToken] = useState('');
  const [withdrawCode, setWithdrawCode] = useState('');

  const onWithdraw = async (code: string) => {
    const receiptCode = code.trim();
    if (!receiptCode) {
      setError('控え番号を入力してください');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(`/public/api/forms/${encodeURIComponent(token)}/withdraw`, {
        method: 'POST',
        body: JSON.stringify({ receipt_code: receiptCode, pin: pin || undefined }),
      });
      writeGuestState(token, { submitted: false, receipt: '' });
      setReceipt(receiptCode);
      setPhase('withdrawn');
    } catch (e) {
      setError(e instanceof Error ? e.message : '取下げに失敗しました');
    } finally {
      setBusy(false);
    }
  };

  const loadGuestDraft = async (resume: string, unlockPin?: string) => {
    const qs = new URLSearchParams({ resume });
    if (unlockPin) qs.set('pin', unlockPin);
    const draft = await api<{
      answers?: Record<string, unknown>;
      receipt_code?: string | null;
      submitter_name?: string | null;
    }>(`/public/api/forms/${encodeURIComponent(token)}/draft?${qs.toString()}`);
    if (!draft.receipt_code) return;
    setValues(draft.answers ?? {});
    if (draft.submitter_name) setSubmitterName(draft.submitter_name);
    setResumeToken(draft.receipt_code);
    setDraftNote('前回の下書きを復元しました。');
  };

  const openForm = (data: PublicForm) => {
    setForm(data);
    document.title = data.title || 'フォーム';
    const saved = token ? readGuestState(token) : {};
    if (saved.submitted && data.allow_multiple === false && !data.requires_pin) {
      setReceipt(saved.receipt || '');
      setPhase('done');
      return;
    }
    setPhase(data.requires_pin ? 'pin' : 'form');
    if (saved.resume) setResumeToken(saved.resume);
    if (data.allow_draft !== false && saved.resume && !data.requires_pin) {
      void loadGuestDraft(saved.resume).catch(() => undefined);
    }
  };

  useEffect(() => {
    if (!token) {
      setError('リンクが不正です。');
      setPhase('error');
      return;
    }
    api<PublicForm>(`/public/api/forms/${encodeURIComponent(token)}`)
      .then(openForm)
      .catch((e: Error) => {
        setError(e.message);
        setPhase('error');
      });
  }, [token]);

  const onExtract = async (kind: 'image' | 'document', file: File) => {
    const data = await fileToDataUrl(file);
    const res = await api<{ extracted?: string }>('/public/api/extract', {
      method: 'POST',
      body: JSON.stringify({ kind, filename: file.name, data }),
    });
    return { extracted: res.extracted || '' };
  };

  const onPostalLookup = async (zip: string) => {
    try {
      return await api<{ prefecture?: string; city?: string; street?: string }>(
        `/public/api/lookup/postal?zip=${encodeURIComponent(zip)}`,
      );
    } catch {
      return lookupPostalDirect(zip);
    }
  };

  const onCorporateLookup = async (number: string) => {
    try {
      return await api<{ company_name?: string }>(
        `/public/api/lookup/corporate?number=${encodeURIComponent(number)}`,
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : '';
      if (msg.includes('13桁') || msg.includes('検査数字')) {
        throw e;
      }
      return { company_name: '' };
    }
  };

  const onUpload = async (file: File, kind: 'file' | 'signature'): Promise<UploadedFile> => {
    const data = await fileToDataUrl(file);
    return api<UploadedFile>(`/public/api/forms/${encodeURIComponent(token)}/files`, {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name,
        data,
        kind,
        pin: pin || undefined,
      }),
    });
  };

  const onUnlock = async () => {
    setBusy(true);
    setError(null);
    try {
      const unlocked = await api<PublicForm>(`/public/api/forms/${encodeURIComponent(token)}`, {
        method: 'POST',
        body: JSON.stringify({ pin }),
      });
      if (unlocked.requires_pin) {
        throw new Error('暗証番号が正しくありません');
      }
      openForm(unlocked);
      const saved = readGuestState(token);
      if (unlocked.allow_draft !== false && saved.resume) {
        void loadGuestDraft(saved.resume, pin).catch(() => undefined);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '暗証番号が正しくありません');
    } finally {
      setBusy(false);
    }
  };

  const onConfirm = () => {
    if (form?.identity_mode === 'required' && !form.has_name_composite && !submitterName.trim()) {
      setError('お名前は必須です');
      return;
    }
    if (definition) {
      const missing = missingRequired(definition.components, values);
      if (missing) {
        setError(`${missing.label}は必須です`);
        return;
      }
    }
    setError(null);
    setPhase('confirm');
  };

  const onSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ receipt_code?: string }>(
        `/public/api/forms/${encodeURIComponent(token)}/submissions`,
        {
          method: 'POST',
          body: JSON.stringify({
            pin: pin || undefined,
            submitter_name: submitterName.trim() || undefined,
            answers: values,
            resume_token: resumeToken || undefined,
          }),
        },
      );
      writeGuestState(token, { receipt: result.receipt_code || '', submitted: true, resume: '' });
      setReceipt(result.receipt_code || '');
      setPhase('done');
    } catch (e) {
      setError(e instanceof Error ? e.message : '送信に失敗しました');
    } finally {
      setBusy(false);
    }
  };

  const definition = form?.definition;
  const rows = definition ? answerRows(definition.components, values) : [];

  return (
    <>
      {phase === 'load' && <p className='hint text-solid-gray-700'>読み込み中...</p>}
      {phase === 'error' && (
        <p className='text-error-1' role='alert'>
          {error}
        </p>
      )}

      {phase === 'pin' && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onUnlock();
          }}
        >
          <h1 className='text-std-20B-160'>{form?.title || 'フォーム'}</h1>
          <p className='mt-2 text-solid-gray-700'>暗証番号を入力してください。</p>
          <div className='mt-4'>
            <Label htmlFor='pf-guest-pin' size='sm'>
              暗証番号（4桁）
            </Label>
            <input
              id='pf-guest-pin'
              className='mt-1 w-full max-w-48 rounded-4 border border-solid-gray-420 px-3 py-2'
              inputMode='numeric'
              maxLength={4}
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              required
            />
          </div>
          {error && (
            <p className='mt-2 text-error-1' role='alert'>
              {error}
            </p>
          )}
          <div className='mt-6'>
            <Button type='submit' variant='solid-fill' size='md' aria-disabled={busy}>
              {busy ? '確認中...' : '開く'}
            </Button>
          </div>
        </form>
      )}

      {phase === 'form' && definition && (
        <>
          <h1 className='text-std-20B-160'>{form?.title || 'フォーム'}</h1>
          {form?.description ? (
            <p className='mt-2 text-solid-gray-700'>{form.description}</p>
          ) : null}
          {form.identity_mode === 'anonymous' || form.has_name_composite ? null : (
          <div className='mt-6'>
            <Label htmlFor='pf-guest-name' size='sm'>
              {form.identity_mode === 'required' ? 'お名前' : 'お名前（任意）'}
            </Label>
            <input
              id='pf-guest-name'
              className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
              value={submitterName}
              onChange={(e) => setSubmitterName(e.target.value)}
              required={form.identity_mode === 'required'}
            />
          </div>
          )}
          {draftNote ? <p className='mt-4 text-solid-gray-700'>{draftNote}</p> : null}
          <div className='mt-4'>
            <FillForm
              definition={definition}
              values={values}
              onChange={(id, v) => setValues((p) => ({ ...p, [id]: v }))}
              onExtract={onExtract}
              onUpload={onUpload}
              onPostalLookup={onPostalLookup}
              onCorporateLookup={onCorporateLookup}
              onWizardChange={(info) => setWizardLast(info.isLast)}
            />
          </div>
          {error && (
            <p className='mt-3 text-error-1' role='alert'>
              {error}
            </p>
          )}
          {wizardLast ? (
            <div className='mt-6 flex flex-wrap gap-2'>
              {form.allow_draft !== false && (
                <Button
                  type='button'
                  variant='outline'
                  size='md'
                  aria-disabled={busy}
                  onClick={() => {
                    void (async () => {
                      setBusy(true);
                      setError(null);
                      try {
                        const result = await api<{ receipt_code?: string }>(
                          `/public/api/forms/${encodeURIComponent(token)}/submissions`,
                          {
                            method: 'POST',
                            body: JSON.stringify({
                              pin: pin || undefined,
                              submitter_name: submitterName.trim() || undefined,
                              answers: values,
                              is_draft: true,
                              resume_token: resumeToken || undefined,
                            }),
                          },
                        );
                        if (result.receipt_code) {
                          setResumeToken(result.receipt_code);
                          writeGuestState(token, { resume: result.receipt_code });
                        }
                        setDraftNote('下書きを保存しました。この端末から続きを入力できます。');
                      } catch (e) {
                        setError(e instanceof Error ? e.message : '下書きの保存に失敗しました');
                      } finally {
                        setBusy(false);
                      }
                    })();
                  }}
                >
                  {busy ? '保存中...' : '下書きを保存'}
                </Button>
              )}
              <Button type='button' variant='solid-fill' size='md' onClick={onConfirm}>
                確認する
              </Button>
            </div>
          ) : null}
          <div className='mt-10 border-t border-solid-gray-300 pt-4'>
            <p className='text-std-16B-150'>控え番号で取り下げる</p>
            <div className='mt-2 flex flex-wrap items-end gap-2'>
              <div>
                <Label htmlFor='pf-guest-withdraw' size='sm'>
                  控え番号
                </Label>
                <input
                  id='pf-guest-withdraw'
                  className='mt-1 w-full max-w-64 rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={withdrawCode}
                  onChange={(e) => setWithdrawCode(e.target.value)}
                />
              </div>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={busy}
                onClick={() => void onWithdraw(withdrawCode)}
              >
                取り下げる
              </Button>
            </div>
          </div>
        </>
      )}

      {phase === 'confirm' && (
        <>
          <h1 className='text-std-20B-160'>内容の確認</h1>
          <p className='mt-2 text-solid-gray-700'>この内容で送信してよろしいですか。</p>
          {submitterName ? <p className='mt-2'>お名前: {submitterName}</p> : null}
          <dl className='mt-4'>
            {rows.map((row) => (
              <div key={row.id} className='mt-3'>
                <dt className='font-bold'>{row.label}</dt>
                <dd className='mt-1 whitespace-pre-wrap'>{row.value}</dd>
              </div>
            ))}
          </dl>
          {error && (
            <p className='mt-3 text-error-1' role='alert'>
              {error}
            </p>
          )}
          <div className='mt-6 flex flex-wrap gap-2'>
            <Button type='button' variant='outline' size='md' onClick={() => setPhase('form')}>
              修正する
            </Button>
            <Button type='button' variant='solid-fill' size='md' aria-disabled={busy} onClick={() => void onSubmit()}>
              {busy ? '送信中...' : '送信する'}
            </Button>
          </div>
        </>
      )}

      {phase === 'done' && (
        <div className='pf-guest-receipt'>
          <h1 className='text-std-20B-160'>受け付けました</h1>
          <p className='mt-2'>
            控え番号: <strong>{receipt}</strong>
          </p>
          <p className='mt-2'>この番号を控えてください。</p>
          {error && (
            <p className='mt-3 text-error-1' role='alert'>
              {error}
            </p>
          )}
          <div className='mt-6'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={busy}
              onClick={() => {
                if (window.confirm('この回答を取り下げますか。内容は残ります。')) {
                  void onWithdraw(receipt);
                }
              }}
            >
              {busy ? '処理中...' : 'この回答を取り下げる'}
            </Button>
          </div>
        </div>
      )}

      {phase === 'withdrawn' && (
        <div className='pf-guest-receipt'>
          <h1 className='text-std-20B-160'>取り下げました</h1>
          <p className='mt-2'>
            控え番号: <strong>{receipt}</strong>
          </p>
          <p className='mt-2'>内容は残ります。誤って取り下げた場合は、受付側に連絡してください。</p>
        </div>
      )}
    </>
  );
};
