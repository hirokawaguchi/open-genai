import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { PatchformSubnav } from './PatchformSubnav';
import type { InboxProcedure } from './types';
import { downloadProcedureExport, usePatchformInbox } from './usePatchform';

const statusLabel = (status: string) => (status === 'published' ? '公開中' : '受付終了');

const ProcedureActions = ({ procedure }: { procedure: InboxProcedure }) => (
  <div className='mt-3 flex flex-wrap gap-2'>
    <Link to={`/patchform/procedures/${procedure.id}`} className='inline-flex'>
      <Button type='button' variant='outline' size='sm'>
        詳細
      </Button>
    </Link>
  </div>
);

export const PatchformInboxPage = () => {
  const { procedureId: pathId } = useParams();
  const [params] = useSearchParams();
  const procedureId = pathId || params.get('procedure') || undefined;
  const { items, procedures, inbox, isLoading, loadError } = usePatchformInbox(procedureId);
  const selected = procedures.find((p) => p.id === procedureId);
  const [exporting, setExporting] = useState<'csv' | 'jsonl' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const download = async (format: 'csv' | 'jsonl') => {
    if (!selected) return;
    setExporting(format);
    setExportError(null);
    try {
      await downloadProcedureExport(selected.id, format);
    } catch {
      setExportError('この手続きの申請を書き出せませんでした。');
    } finally {
      setExporting(null);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={`申請受付 · ${PATCHFORM_LABEL}`} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '申請受付', to: '/patchform/inbox' },
            ...(selected ? [{ label: selected.name }] : []),
          ]}
        />
        <div className='flex flex-col gap-2'>
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>
            {selected ? selected.name : '申請受付'}
          </h1>
          <PatchformSubnav current='inbox' />
          <p className='text-std-16N-170 text-solid-gray-700'>
            {selected
              ? 'この手続きに受付された申請です。案内番号を開くと、提出済みの回答を見られます。'
              : '公開中、または申請が届いている手続きです。手続きを選ぶと申請一覧を見られます。'}
          </p>
        </div>

        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}

        {selected ? (
          <section className='flex flex-col gap-3'>
            <p className='text-dns-14N-130 text-solid-gray-600'>
              {statusLabel(selected.status)}
              {selected.guide_title ? ` / ${selected.guide_title}` : ''}
              {` / 申請 ${selected.bundle_count} 件`}
            </p>
            <ProcedureActions procedure={selected} />
            <div className='flex flex-wrap gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={exporting != null}
                onClick={() => void download('csv')}
              >
                {exporting === 'csv' ? '書き出し中...' : 'CSVをまとめてダウンロード'}
              </Button>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={exporting != null}
                onClick={() => void download('jsonl')}
              >
                {exporting === 'jsonl' ? '書き出し中...' : 'JSONLをまとめてダウンロード'}
              </Button>
            </div>
            {exportError && (
              <p className='text-error-1' role='alert'>
                {exportError}
              </p>
            )}
            <h2 className='mt-4 text-std-18B-160'>届いた申請</h2>
            {inbox && (
              <p className='text-dns-14N-130 text-solid-gray-600'>{inbox.bundle_count} 件</p>
            )}
            {items.length === 0 ? (
              <p className='text-solid-gray-600'>まだ届いた申請はありません。</p>
            ) : (
              <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                {items.map((item) => (
                  <li key={`${item.kind}-${item.id}`} className='py-3'>
                    <Link
                      to={`/patchform/applications/${item.id}`}
                      className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                    >
                      案内番号 {item.label}
                    </Link>
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      {item.total != null ? `${item.submitted}/${item.total} 提出` : ''}
                      {' / '}
                      {new Date(item.created_at).toLocaleString('ja-JP')}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p className='text-std-16N-170'>
              <Link to='/patchform/inbox' className='text-blue-900 underline-offset-2 hover:underline'>
                手続き一覧へ戻る
              </Link>
            </p>
          </section>
        ) : (
          <section className='flex flex-col gap-3'>
            <h2 className='text-std-18B-160'>手続き</h2>
            {procedures.length === 0 ? (
              <p className='text-solid-gray-600'>
                公開中の手続きも、届いた申請もありません。先に「手続きを公開」してください。
              </p>
            ) : (
              <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                {procedures.map((item) => (
                  <li key={item.id} className='py-3'>
                    <Link
                      to={`/patchform/inbox/${item.id}`}
                      className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                    >
                      {item.name}
                    </Link>
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      {statusLabel(item.status)}
                      {item.guide_title ? ` / ${item.guide_title}` : ''}
                      {` / 申請 ${item.bundle_count} 件`}
                      {' / '}
                      {new Date(item.updated_at).toLocaleString('ja-JP')}
                    </p>
                    <ProcedureActions procedure={item} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </LayoutBody>
  );
};
