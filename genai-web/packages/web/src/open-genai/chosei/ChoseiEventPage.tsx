import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { formatDateTime, STATUS_LABEL, STATUS_MARK } from './format';
import type { InviteDraftResult, RecommendResult, ResponseStatus } from './types';
import { copyToClipboard } from '@/utils/copyToClipboard';
import { toAbsoluteUrl } from '@/utils/toAbsoluteUrl';
import {
  downloadChoseiCarrier,
  useChoseiActions,
  useChoseiAssist,
  useChoseiEvent,
} from './useChosei';

export const ChoseiEventPage = () => {
  const { eventId } = useParams<{ eventId: string }>();
  const navigate = useNavigate();
  const { detail, isLoading, loadError, mutate } = useChoseiEvent(eventId);
  const { submitResponse, remove, submitting, error, setError } = useChoseiActions();
  const {
    recommend,
    draftInvite,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = useChoseiAssist();

  const [name, setName] = useState('');
  const [pin, setPin] = useState('');
  const [answers, setAnswers] = useState<Record<number, ResponseStatus>>({});
  const [deletePin, setDeletePin] = useState('');
  const [copied, setCopied] = useState(false);
  const [recommendation, setRecommendation] = useState<RecommendResult | null>(null);
  const [invite, setInvite] = useState<InviteDraftResult | null>(null);

  const dates = detail?.dates ?? [];

  const participantNames = useMemo(() => {
    const names: string[] = [];
    const seen = new Set<string>();
    for (const r of detail?.responses ?? []) {
      if (!seen.has(r.participant_name)) {
        seen.add(r.participant_name);
        names.push(r.participant_name);
      }
    }
    return names;
  }, [detail]);

  const statusByParticipant = useMemo(() => {
    const map = new Map<string, Record<number, ResponseStatus>>();
    for (const r of detail?.responses ?? []) {
      const cur = map.get(r.participant_name) ?? {};
      cur[r.event_date_id] = r.status;
      map.set(r.participant_name, cur);
    }
    return map;
  }, [detail]);

  if (isLoading) {
    return (
      <LayoutBody>
        <PageTitle title='日程調整' />
        <div className='p-8 text-solid-gray-600'>読み込み中...</div>
      </LayoutBody>
    );
  }

  if (loadError || !detail) {
    return (
      <LayoutBody>
        <PageTitle title='日程調整' />
        <div className='mx-auto max-w-(--page-width) p-8'>
          <p className='text-error-1' role='alert'>
            {loadError || 'イベントが見つかりません'}
          </p>
          <Link to='/chosei' className='mt-4 inline-block text-blue-900 underline'>
            一覧へ戻る
          </Link>
        </div>
      </LayoutBody>
    );
  }

  const ev = detail.event;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!eventId || !name.trim()) {
      setError('お名前を入力してください。');
      return;
    }
    const responses = dates.map((d) => ({
      event_date_id: d.id,
      status: answers[d.id] ?? ('ng' as ResponseStatus),
    }));
    const ok = await submitResponse(eventId, {
      participant_name: name.trim(),
      password: pin.trim() || undefined,
      responses,
    });
    if (ok) {
      await mutate();
      setPin('');
    }
  };

  const onDelete = async () => {
    if (!eventId) return;
    if (!window.confirm('このイベントを削除しますか？')) return;
    const ok = await remove(eventId, deletePin.trim() || undefined);
    if (ok) navigate('/chosei');
  };

  const publicUrl = toAbsoluteUrl(ev.public_url);

  const copyPublic = async () => {
    const ok = await copyToClipboard(publicUrl);
    if (ok) {
      setError(null);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
      return;
    }
    setError('コピーに失敗しました。URL を手動で選択してください。');
  };

  return (
    <LayoutBody>
      <PageTitle title={ev.title} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: '日程調整', to: '/chosei' },
            { label: ev.title },
          ]}
        />
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h1 className='text-std-20B-160 lg:text-std-24B-150'>{ev.title}</h1>
            <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
              回答者{participantNames.length}名
              {ev.creator_name ? ` · 作成者: ${ev.creator_name}` : ''}
            </p>
            {ev.description && (
              <p className='mt-3 whitespace-pre-wrap text-std-16N-170 text-solid-gray-700'>
                {ev.description}
              </p>
            )}
          </div>
          <div className='flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() => navigate(`/chosei/events/${ev.id}/edit`)}
            >
              編集
            </Button>
          </div>
        </div>

        <section className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
          <h2 className='text-std-16B-150'>外部共有 URL</h2>
          <p className='mt-1 break-all text-dns-14N-130 text-blue-900'>{publicUrl}</p>
          <div className='mt-3 flex flex-wrap gap-2'>
            <Button type='button' variant='solid-fill' size='sm' onClick={copyPublic}>
              {copied ? 'コピーしました' : 'URL をコピー'}
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() => downloadChoseiCarrier(ev.id, 'txt')}
            >
              リンクファイル (.txt)
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() => downloadChoseiCarrier(ev.id, 'html')}
            >
              リンクファイル (.html)
            </Button>
          </div>
          <p className='mt-2 text-dns-14N-130 text-solid-gray-600'>
            LGWAN から外部 URL に届かない場合はリンクファイルを持ち出してください。
          </p>
        </section>

        <section>
          <h2 className='mb-1 text-std-18B-160'>日程候補・回答一覧</h2>
          <p className='mb-3 text-dns-14N-130 text-solid-gray-600'>
            行が日程、列が回答者です。○参加可 / △検討中 / ×不可
          </p>
          <div className='overflow-x-auto'>
            <table className='w-max min-w-full border-collapse text-dns-14N-130'>
              <thead>
                <tr className='bg-solid-gray-50'>
                  <th className='sticky left-0 z-1 border border-solid-gray-300 bg-solid-gray-50 px-3 py-2 text-left'>
                    日程
                  </th>
                  <th className='border border-solid-gray-300 px-3 py-2 text-center' title='参加可'>
                    ○
                  </th>
                  <th className='border border-solid-gray-300 px-3 py-2 text-center' title='検討中'>
                    △
                  </th>
                  <th className='border border-solid-gray-300 px-3 py-2 text-center' title='不可'>
                    ×
                  </th>
                  {participantNames.map((pname) => (
                    <th
                      key={pname}
                      className='max-w-32 truncate border border-solid-gray-300 px-3 py-2 text-center'
                      title={pname}
                    >
                      {pname}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dates.map((d) => {
                  const st = detail.statistics[String(d.id)] || {
                    ok: 0,
                    maybe: 0,
                    ng: 0,
                  };
                  return (
                    <tr key={d.id}>
                      <th
                        scope='row'
                        className='sticky left-0 z-1 border border-solid-gray-300 bg-white px-3 py-2 text-left font-normal'
                      >
                        {formatDateTime(d.date_time, d.end_time, d.is_all_day)}
                        {d.is_all_day ? '（終日）' : ''}
                      </th>
                      <td className='border border-solid-gray-300 px-3 py-2 text-center tabular-nums text-solid-gray-700'>
                        {st.ok}
                      </td>
                      <td className='border border-solid-gray-300 px-3 py-2 text-center tabular-nums text-solid-gray-700'>
                        {st.maybe}
                      </td>
                      <td className='border border-solid-gray-300 px-3 py-2 text-center tabular-nums text-solid-gray-700'>
                        {st.ng}
                      </td>
                      {participantNames.map((pname) => {
                        const status = statusByParticipant.get(pname)?.[d.id];
                        return (
                          <td
                            key={pname}
                            className='border border-solid-gray-300 px-3 py-2 text-center text-std-16B-150'
                            title={status ? STATUS_LABEL[status] : '未回答'}
                          >
                            <span
                              className={
                                status === 'ok'
                                  ? 'text-green-800'
                                  : status === 'maybe'
                                    ? 'text-orange-800'
                                    : status === 'ng'
                                      ? 'text-solid-gray-600'
                                      : 'text-solid-gray-420'
                              }
                            >
                              {status ? STATUS_MARK[status] : '—'}
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {participantNames.length === 0 && (
            <p className='mt-3 text-dns-14N-130 text-solid-gray-600'>
              まだ回答がありません。下のフォームから回答できます。
            </p>
          )}

          <div className='mt-4 flex flex-wrap items-start gap-3'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              aria-disabled={assistBusy}
              onClick={async () => {
                if (!eventId) return;
                setAssistError(null);
                const res = await recommend(eventId);
                if (res) setRecommendation(res);
              }}
            >
              {assistBusy ? '提案中...' : '最適日を提案（LLM）'}
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              aria-disabled={assistBusy}
              onClick={async () => {
                if (!eventId) return;
                setAssistError(null);
                const res = await draftInvite(eventId, '丁寧');
                if (res) setInvite(res);
              }}
            >
              {assistBusy ? '作成中...' : '案内文を下書き（LLM）'}
            </Button>
          </div>
          {assistError && (
            <p className='mt-2 text-error-1' role='alert'>
              {assistError}
            </p>
          )}
          {recommendation && (
            <div className='mt-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
              <p className='text-std-16B-150'>最適日の提案</p>
              <p className='mt-1 text-std-16N-170'>
                {recommendation.recommended_date_time
                  ? formatDateTime(recommendation.recommended_date_time)
                  : '（候補なし）'}
                <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>
                  （{recommendation.source === 'llm' ? 'LLM' : '簡易集計'}
                  {recommendation.model ? ` / ${recommendation.model}` : ''}）
                </span>
              </p>
              <p className='mt-2 whitespace-pre-wrap text-dns-14N-130 text-solid-gray-700'>
                {recommendation.reasoning}
              </p>
            </div>
          )}
          {invite && (
            <div className='mt-3 rounded-8 border border-solid-gray-300 p-4'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <p className='text-std-16B-150'>案内文下書き</p>
                <Button
                  type='button'
                  variant='text'
                  size='sm'
                  onClick={async () => {
                    const text = `${invite.subject}\n\n${invite.body}`;
                    const ok = await copyToClipboard(text);
                    if (!ok) {
                      setAssistError('コピーに失敗しました。');
                    }
                  }}
                >
                  件名＋本文をコピー
                </Button>
              </div>
              <p className='mt-2 text-dns-14N-130 text-solid-gray-600'>件名</p>
              <p className='text-std-16N-170'>{invite.subject}</p>
              <p className='mt-3 text-dns-14N-130 text-solid-gray-600'>本文</p>
              <pre className='mt-1 whitespace-pre-wrap rounded-4 bg-solid-gray-50 p-3 text-dns-14N-130 text-solid-gray-800'>
                {invite.body}
              </pre>
              {invite.tips && (
                <p className='mt-2 text-dns-14N-130 text-solid-gray-600'>{invite.tips}</p>
              )}
            </div>
          )}
        </section>

        <section>
          <h2 className='mb-3 text-std-18B-160'>出欠を入力する</h2>
          <form onSubmit={onSubmit} className='flex flex-col gap-4'>
            <div className='grid gap-4 md:grid-cols-2'>
              <div>
                <Label htmlFor='res-name' size='sm'>
                  お名前
                </Label>
                <input
                  id='res-name'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>
              <div>
                <Label htmlFor='res-pin' size='sm'>
                  暗証番号（4桁）
                </Label>
                <input
                  id='res-pin'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  inputMode='numeric'
                  maxLength={4}
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  placeholder='初回は設定、再回答時は同じ番号'
                />
              </div>
            </div>
            <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
              {dates.map((d) => (
                <li
                  key={d.id}
                  className='flex flex-col gap-2 py-3 md:flex-row md:items-center md:justify-between'
                >
                  <span className='text-std-16N-170'>
                    {formatDateTime(d.date_time, d.end_time, d.is_all_day)}
                    {d.is_all_day ? '（終日）' : ''}
                  </span>
                  <div className='flex flex-wrap gap-2'>
                    {(['ok', 'maybe', 'ng'] as ResponseStatus[]).map((st) => (
                      <label
                        key={st}
                        className={`cursor-pointer rounded-4 border px-3 py-1 text-dns-14N-130 ${
                          (answers[d.id] ?? 'ng') === st
                            ? 'border-blue-900 bg-blue-50 text-blue-900'
                            : 'border-solid-gray-300'
                        }`}
                      >
                        <input
                          type='radio'
                          className='sr-only'
                          name={`st-${d.id}`}
                          checked={(answers[d.id] ?? 'ng') === st}
                          onChange={() => setAnswers((prev) => ({ ...prev, [d.id]: st }))}
                        />
                        {STATUS_MARK[st]} {STATUS_LABEL[st]}
                      </label>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
            {error && (
              <p className='text-error-1' role='alert'>
                {error}
              </p>
            )}
            <div>
              <Button type='submit' variant='solid-fill' size='md' aria-disabled={submitting}>
                {submitting ? '送信中...' : '回答を送信'}
              </Button>
            </div>
          </form>
        </section>

        <section className='border-t border-solid-gray-300 pt-6'>
          <h2 className='mb-2 text-std-16B-150 text-solid-gray-700'>イベントを削除</h2>
          <p className='mb-3 text-dns-14N-130 text-solid-gray-600'>
            作成者本人以外はイベント暗証番号が必要です。
          </p>
          <div className='flex flex-wrap items-end gap-3'>
            <div>
              <Label htmlFor='del-pin' size='sm'>
                イベント暗証番号
              </Label>
              <input
                id='del-pin'
                className='mt-1 w-40 rounded-4 border border-solid-gray-420 px-3 py-2'
                inputMode='numeric'
                maxLength={4}
                value={deletePin}
                onChange={(e) => setDeletePin(e.target.value)}
              />
            </div>
            <Button type='button' variant='outline' size='sm' onClick={onDelete}>
              削除する
            </Button>
          </div>
        </section>
      </div>
    </LayoutBody>
  );
};
