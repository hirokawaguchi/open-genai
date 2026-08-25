import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { PatchformProcedureCoach } from './PatchformProcedureCoach';
import { answerRows } from './runtime/formatAnswer';
import { downloadApplicationExport, usePatchformApplication } from './usePatchform';

const statusLabel: Record<string, string> = {
  none: '未提出',
  draft: '下書き',
  submitted: '提出済',
  withdrawn: '取下げ',
};

export const PatchformApplicationPage = () => {
  const { applicationId } = useParams();
  const { application, isLoading, loadError } = usePatchformApplication(applicationId);
  const notice = application?.notice;
  const [exporting, setExporting] = useState<'csv' | 'jsonl' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const download = async (format: 'csv' | 'jsonl') => {
    if (!applicationId) return;
    setExporting(format);
    setExportError(null);
    try {
      await downloadApplicationExport(applicationId, format);
    } catch {
      setExportError('この申請を書き出せませんでした。');
    } finally {
      setExporting(null);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={application?.procedure_name || '申請'} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '申請受付', to: '/patchform/inbox' },
            ...(application?.procedure_id
              ? [{ label: application.procedure_name, to: `/patchform/inbox/${application.procedure_id}` }]
              : []),
            { label: application?.token || '申請' },
          ]}
        />
        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}
        {application && (
          <>
            <div className='flex flex-col gap-2'>
              <h1 className='text-std-20B-160 lg:text-std-24B-150'>{application.procedure_name}</h1>
              <p className='text-std-16N-170 text-solid-gray-700'>
                案内番号: {application.token}。この番号の束に入った様式だけを、下から記入します。
              </p>
              {application.procedure_description && (
                <p className='text-std-16N-170 text-solid-gray-700'>
                  {application.procedure_description}
                </p>
              )}
              <p className='text-dns-14N-130 text-solid-gray-600'>
                公開 URL: {application.public_url}
              </p>
              <div className='mt-2 flex flex-wrap gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={exporting != null}
                  onClick={() => void download('csv')}
                >
                  {exporting === 'csv' ? '書き出し中...' : 'CSVをダウンロード'}
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={exporting != null}
                  onClick={() => void download('jsonl')}
                >
                  {exporting === 'jsonl' ? '書き出し中...' : 'JSONLをダウンロード'}
                </Button>
              </div>
              {exportError && (
                <p className='text-error-1' role='alert'>
                  {exportError}
                </p>
              )}
            </div>
            <PatchformProcedureCoach
              title='この申請でやること'
              lead='提出済みの様式は、下に回答内容が出ます。未提出なら様式を開いて送ってください。'
              steps={[
                {
                  id: 'open',
                  label: '未提出の様式を開く',
                  done: application.forms.length === 0 || application.forms.every((f) => f.status === 'submitted'),
                  hint: '庁内から開いても、公開 URL から開いても同じ束に付きます。',
                  action: (() => {
                    const next = application.forms.find((f) => f.status === 'none' || f.status === 'draft');
                    return next
                      ? {
                          label: `「${next.title}」を開く`,
                          to: `/patchform/${next.id}?app=${encodeURIComponent(application.token)}`,
                        }
                      : undefined;
                  })(),
                },
                {
                  id: 'done',
                  label: '必要な様式を出し終える',
                  done: application.forms.length > 0 && application.forms.every((f) => f.status === 'submitted'),
                  hint: `${application.forms.filter((f) => f.status === 'submitted').length} / ${application.forms.length} 提出済み`,
                },
              ]}
            />
            {(notice?.notes || []).length > 0 && (
              <section>
                <h2 className='text-std-18B-160'>解説</h2>
                <ul className='mt-2 list-disc pl-5 text-std-16N-170'>
                  {notice?.notes?.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </section>
            )}
            {(notice?.prepare || []).length > 0 && (
              <section>
                <h2 className='text-std-18B-160'>準備するもの</h2>
                <ul className='mt-2 list-disc pl-5 text-std-16N-170'>
                  {notice?.prepare?.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </section>
            )}
            <section>
              <h2 className='text-std-18B-160'>様式</h2>
              {application.forms.length === 0 ? (
                <p className='mt-2 text-solid-gray-600'>この回答では足す様式がありません。</p>
              ) : (
                <ul className='mt-2 divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                  {application.forms.map((f) => {
                    const rows =
                      f.status === 'submitted' && f.definition && f.answers
                        ? answerRows(f.definition.components, f.answers)
                        : [];
                    return (
                    <li key={f.id} className='py-3'>
                      <Link
                        to={`/patchform/${f.id}?app=${encodeURIComponent(application.token)}`}
                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                      >
                        {f.title}
                      </Link>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        {statusLabel[f.status] || f.status}
                        {f.receipt_code ? ` / 控え番号 ${f.receipt_code}` : ''}
                        {f.submitted_at
                          ? ` / ${new Date(f.submitted_at).toLocaleString('ja-JP')}`
                          : ''}
                      </p>
                      {rows.length > 0 ? (
                        <dl className='mt-2 grid gap-1 text-std-16N-170'>
                          {rows.map((row) => (
                            <div key={row.id} className='grid gap-0.5 sm:grid-cols-[12rem_1fr]'>
                              <dt className='text-solid-gray-600'>{row.label}</dt>
                              <dd className='whitespace-pre-wrap text-solid-gray-900'>{row.value}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}
                    </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
