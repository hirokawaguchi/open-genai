import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { ADMIN_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { useTeamAuth } from '@/features/teams/hooks/useTeamAuth';
import { LayoutBody } from '@/layout/LayoutBody';
import { AUDIT_EXAPP_ID } from '@/layout/navItems';
import { PageTitle } from '@/components/PageTitle';
import { AUDIT_ACTION_OPTIONS, type AuditFilters, type AuditLog } from './types';
import { useAuditExport, useAuditLogs } from './useAuditLogs';

const DEFAULT_FILTERS: AuditFilters = {
  userId: '',
  action: 'all',
  q: '',
  fromDate: '',
  toDate: '',
  limit: 50,
};

const LIMIT_OPTIONS = [20, 50, 100, 200, 500];

const actionLabel = (action: string): string =>
  AUDIT_ACTION_OPTIONS.find((o) => o.value === action)?.title ?? action;

/** epoch ms を JST（UTC+9）の読みやすい文字列にする。 */
const formatTs = (ts: number): string => {
  if (!ts) {
    return '-';
  }
  // +9 時間ずらして UTC 表記（toISOString）で読むと JST の壁時計時刻になる。
  const jst = new Date(ts + 9 * 60 * 60 * 1000);
  return `${jst.toISOString().replace('T', ' ').slice(0, 19)} JST`;
};

const excerpt = (text: string | null, max = 60): string => {
  if (!text) {
    return '';
  }
  return text.length > max ? `${text.slice(0, max)}…` : text;
};

/**
 * 監査ログ参照の専用ページ（管理者限定・OpenGENAI 拡張）。
 * 源内の汎用 exApp フォーム（Markdown 出力）では詳細確認や全文閲覧・エクスポートが
 * しづらいため、フィルタ→テーブル→全文→エクスポートを専用ページとして提供する。
 */
export const AuditLogsPage = () => {
  const { isSystemAdminGroup } = useTeamAuth();

  // 入力中の下書きと、実際に検索へ反映した条件を分離する。
  const [draft, setDraft] = useState<AuditFilters>(DEFAULT_FILTERS);
  const [applied, setApplied] = useState<AuditFilters>(DEFAULT_FILTERS);
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { items, total, isLoading, forbidden, loadError } = useAuditLogs(applied, offset);
  const { exportLogs, exporting, exportError } = useAuditExport(applied);

  const page = Math.floor(offset / applied.limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / applied.limit));
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + applied.limit, total);

  const search = () => {
    setApplied(draft);
    setOffset(0);
    setExpandedId(null);
  };

  const reset = () => {
    setDraft(DEFAULT_FILTERS);
    setApplied(DEFAULT_FILTERS);
    setOffset(0);
    setExpandedId(null);
  };

  const gotoPage = (nextOffset: number) => {
    setOffset(Math.max(0, nextOffset));
    setExpandedId(null);
  };

  const header = (
    <ManagedAppHeader
      teamId={ADMIN_EXAPPS_TEAM_ID}
      exAppId={AUDIT_EXAPP_ID}
      fallbackTitle='監査ログ'
      fallbackDescription='利用者単位の利用状況・利用内容ログを確認します（管理者限定）。監査ログには入力・出力の本文が含まれる場合があります。取り扱いに注意してください。'
      fallbackHowTo={
        <>
          <p>・条件を入力して「検索」を押すと絞り込めます。日付は JST の 0:00〜23:59 で扱います。</p>
          <p>・各行の「全文」を開くと、入力・出力の本文をそのまま確認できます。</p>
          <p>・「エクスポート」で、現在の期間（開始日・終了日）の全件を JSONL でダウンロードできます。</p>
        </>
      }
    />
  );

  if (!isSystemAdminGroup) {
    return (
      <LayoutBody>
        <PageTitle title='監査ログ' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          {header}
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧には管理者権限が必要です。
          </p>
        </div>
      </LayoutBody>
    );
  }

  return (
    <LayoutBody>
      <PageTitle title='監査ログ' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        {header}

        {/* 絞り込みフォーム */}
        <div className='grid grid-cols-1 gap-4 rounded-8 border border-solid-gray-300 p-4 sm:grid-cols-2 lg:grid-cols-3'>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='audit-user' size='sm'>
              ユーザーID
            </Label>
            <Input
              id='audit-user'
              blockSize='md'
              value={draft.userId}
              onChange={(e) => setDraft({ ...draft, userId: e.target.value })}
            />
          </div>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='audit-action' size='sm'>
              アクション種別
            </Label>
            <Select
              id='audit-action'
              blockSize='md'
              value={draft.action}
              onChange={(e) => setDraft({ ...draft, action: e.target.value })}
            >
              {AUDIT_ACTION_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.title}
                </option>
              ))}
            </Select>
          </div>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='audit-q' size='sm'>
              キーワード（本文）
            </Label>
            <Input
              id='audit-q'
              blockSize='md'
              value={draft.q}
              onChange={(e) => setDraft({ ...draft, q: e.target.value })}
            />
          </div>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='audit-from' size='sm'>
              開始日（JST）
            </Label>
            <Input
              id='audit-from'
              type='date'
              blockSize='md'
              value={draft.fromDate}
              onChange={(e) => setDraft({ ...draft, fromDate: e.target.value })}
            />
          </div>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='audit-to' size='sm'>
              終了日（JST）
            </Label>
            <Input
              id='audit-to'
              type='date'
              blockSize='md'
              value={draft.toDate}
              onChange={(e) => setDraft({ ...draft, toDate: e.target.value })}
            />
          </div>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='audit-limit' size='sm'>
              表示件数
            </Label>
            <Select
              id='audit-limit'
              blockSize='md'
              value={String(draft.limit)}
              onChange={(e) => setDraft({ ...draft, limit: Number(e.target.value) })}
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}件
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className='flex flex-wrap items-center gap-3'>
          <Button type='button' variant='solid-fill' size='md' onClick={search}>
            検索
          </Button>
          <Button type='button' variant='outline' size='md' onClick={reset}>
            条件をクリア
          </Button>
          <Button
            type='button'
            variant='outline'
            size='md'
            onClick={exportLogs}
            aria-disabled={exporting || undefined}
          >
            {exporting ? 'エクスポート中...' : 'エクスポート（JSONL）'}
          </Button>
        </div>

        {exportError && (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            {exportError}
          </p>
        )}

        {/* 結果 */}
        {forbidden ? (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧には管理者権限が必要です。
          </p>
        ) : loadError ? (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            {loadError}
          </p>
        ) : (
          <div className='flex flex-col gap-3'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <SupportText>
                {total === 0
                  ? '該当するログはありません。'
                  : `全 ${total} 件中 ${rangeStart}〜${rangeEnd} 件を表示`}
              </SupportText>
              {isLoading && <SupportText>読み込み中...</SupportText>}
            </div>

            {items.length > 0 && (
              <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
                <table className='w-full border-collapse text-left text-dns-14N-130'>
                  <thead className='bg-solid-gray-50 text-solid-gray-700'>
                    <tr>
                      <th className='whitespace-nowrap px-3 py-2 font-bold'>日時（JST）</th>
                      <th className='whitespace-nowrap px-3 py-2 font-bold'>ユーザー</th>
                      <th className='whitespace-nowrap px-3 py-2 font-bold'>アクション</th>
                      <th className='whitespace-nowrap px-3 py-2 font-bold'>モデル</th>
                      <th className='whitespace-nowrap px-3 py-2 font-bold'>入力/出力</th>
                      <th className='px-3 py-2 font-bold'>内容抜粋</th>
                      <th className='px-3 py-2 font-bold'>全文</th>
                    </tr>
                  </thead>
                  <tbody className='divide-y divide-solid-gray-300'>
                    {items.map((log) => (
                      <AuditRow
                        key={log.id}
                        log={log}
                        expanded={expandedId === log.id}
                        onToggle={() =>
                          setExpandedId((cur) => (cur === log.id ? null : log.id))
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {total > 0 && (
              <div className='flex items-center justify-between gap-3'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => gotoPage(offset - applied.limit)}
                  aria-disabled={offset === 0 || undefined}
                >
                  前へ
                </Button>
                <span className='text-dns-14N-130 text-solid-gray-700'>
                  {page} / {totalPages} ページ
                </span>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => gotoPage(offset + applied.limit)}
                  aria-disabled={rangeEnd >= total || undefined}
                >
                  次へ
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </LayoutBody>
  );
};

type RowProps = {
  log: AuditLog;
  expanded: boolean;
  onToggle: () => void;
};

const AuditRow = ({ log, expanded, onToggle }: RowProps) => {
  const hasContent = !!(log.inputText || log.outputText);
  return (
    <>
      <tr className='align-top text-solid-gray-900'>
        <td className='whitespace-nowrap px-3 py-2'>{formatTs(log.ts)}</td>
        <td className='px-3 py-2'>
          <span className='block max-w-[12rem] truncate' title={log.userEmail || log.userId}>
            {log.userEmail || log.userId || '-'}
          </span>
        </td>
        <td className='whitespace-nowrap px-3 py-2'>{actionLabel(log.action)}</td>
        <td className='whitespace-nowrap px-3 py-2'>{log.model || '-'}</td>
        <td className='whitespace-nowrap px-3 py-2'>
          {(log.inputChars ?? 0).toLocaleString()} / {(log.outputChars ?? 0).toLocaleString()}
        </td>
        <td className='px-3 py-2'>
          <span className='block max-w-[20rem] text-solid-gray-700'>
            {excerpt(log.inputText || log.outputText) || '-'}
          </span>
        </td>
        <td className='whitespace-nowrap px-3 py-2'>
          {hasContent ? (
            <Button type='button' variant='text' size='sm' onClick={onToggle}>
              {expanded ? '閉じる' : '全文'}
            </Button>
          ) : (
            <span className='text-solid-gray-500'>-</span>
          )}
        </td>
      </tr>
      {expanded && hasContent && (
        <tr>
          <td colSpan={7} className='bg-solid-gray-50 px-3 py-3'>
            <div className='flex flex-col gap-4'>
              {log.inputText && (
                <div className='flex flex-col gap-1'>
                  <span className='text-dns-14B-130 text-solid-gray-700'>入力</span>
                  <pre className='whitespace-pre-wrap break-words rounded-8 border border-solid-gray-300 bg-white p-3 text-dns-14N-130 text-solid-gray-900'>
                    {log.inputText}
                  </pre>
                </div>
              )}
              {log.outputText && (
                <div className='flex flex-col gap-1'>
                  <span className='text-dns-14B-130 text-solid-gray-700'>出力</span>
                  <pre className='whitespace-pre-wrap break-words rounded-8 border border-solid-gray-300 bg-white p-3 text-dns-14N-130 text-solid-gray-900'>
                    {log.outputText}
                  </pre>
                </div>
              )}
              <dl className='grid grid-cols-2 gap-x-4 gap-y-1 text-dns-14N-130 text-solid-gray-700 sm:grid-cols-3'>
                <MetaItem label='ユースケース' value={log.usecase} />
                <MetaItem label='パス' value={log.path} />
                <MetaItem label='ステータス' value={log.status?.toString()} />
                <MetaItem label='応答時間(ms)' value={log.latencyMs?.toString()} />
                <MetaItem label='IP' value={log.ip} />
                <MetaItem label='チャットID' value={log.chatId} />
              </dl>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};

const MetaItem = ({ label, value }: { label: string; value: string | null | undefined }) => (
  <div className='flex gap-1'>
    <dt className='font-bold'>{label}:</dt>
    <dd className='min-w-0 truncate' title={value ?? undefined}>
      {value || '-'}
    </dd>
  </div>
);
