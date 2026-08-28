import { Link, useNavigate, useParams } from 'react-router';
import { PiFoldersBold, PiPlusBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { usePatchformMyApplications, usePatchformProcedure } from './usePatchform';

const statusStyle = (status: string): string => {
  switch (status) {
    case '提出済':
    case '完了':
      return 'border-green-600 bg-green-50 text-green-800';
    case '作業中':
      return 'border-blue-900 bg-blue-50 text-blue-900';
    case '取下げ':
      return 'border-error-1 bg-red-50 text-error-1';
    default:
      return 'border-solid-gray-420 bg-solid-gray-50 text-solid-gray-700';
  }
};

/**
 * 手続きを開始する画面（庁内）。docmaker.net の「案件を新規作成／既存案件を開く」に相当。
 * 公開手続きを開くと、マイ手続きの案件（プロジェクト）として展開する（project-first）。
 * 案内（ナビ）への回答は案件の中で行い、提出書類一覧が育つ。
 */
export const PatchformApplyPage = () => {
  const { procedureId } = useParams();
  const navigate = useNavigate();
  const { procedure, isLoading: procLoading, loadError: procError } =
    usePatchformProcedure(procedureId);
  const { applications, isLoading: mineLoading } = usePatchformMyApplications();

  const published = procedure?.status === 'published';
  const mine = applications.filter((a) => a.procedure_id === procedureId);
  const active = mine.filter((a) => a.status.effective !== '取下げ');

  const onStart = () => {
    if (!procedureId) return;
    navigate(`/patchform/apply/${procedureId}/wizard`);
  };

  return (
    <LayoutBody>
      <PageTitle title={procedure?.name || '庁内申請'} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: 'マイ手続き', to: '/patchform/my' },
            { label: procedure?.name || '庁内申請' },
          ]}
        />
        <div className='flex flex-col gap-2'>
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>
            {procedure?.name || '庁内申請'}
          </h1>
          {procedure?.description ? (
            <p className='text-std-16N-170 text-solid-gray-700'>{procedure.description}</p>
          ) : null}
          <p className='text-std-16N-170 text-solid-gray-700'>
            この手続きは「マイ手続き」の案件として進めます。始めると案内（ナビ）に答えるだけで提出書類一覧ができ、記入や添付を少しずつ進められます。
          </p>
        </div>

        {(procLoading || mineLoading) && <p className='text-solid-gray-600'>読み込み中...</p>}
        {procError && (
          <p className='text-error-1' role='alert'>
            {procError}
          </p>
        )}
        {procedure && !published ? (
          <p className='text-solid-gray-700'>この手続きは受付していません。</p>
        ) : null}

        {published ? (
          <>
            {active.length > 0 ? (
              <section className='flex flex-col gap-3'>
                <h2 className='flex items-center gap-2 text-std-18B-160'>
                  <PiFoldersBold className='size-5' />
                  進行中の手続き
                </h2>
                <p className='text-std-16N-170 text-solid-gray-700'>
                  この手続きで作りかけの案件があります。続きから進められます。
                </p>
                <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                  {active.map((a) => (
                    <li key={a.id} className='flex flex-wrap items-center gap-3 py-3'>
                      <div className='min-w-0 flex-1'>
                        <Link
                          to={`/patchform/applications/${a.id}?from=my`}
                          className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                        >
                          {a.title}
                        </Link>
                        <p className='text-dns-14N-130 text-solid-gray-600'>
                          {a.total > 0 ? `書類 ${a.done}/${a.total} / ` : ''}
                          更新 {new Date(a.updated_at).toLocaleString('ja-JP')}
                        </p>
                      </div>
                      <span
                        className={`rounded-4 border px-2 py-0.5 text-dns-14N-130 ${statusStyle(a.status.effective)}`}
                      >
                        {a.status.effective}
                      </span>
                      <Link to={`/patchform/applications/${a.id}?from=my`} className='inline-flex'>
                        <Button type='button' variant='outline' size='sm'>
                          続きから
                        </Button>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
              <h2 className='flex items-center gap-2 text-std-18B-160'>
                <PiPlusBold className='size-5' />
                {active.length > 0 ? 'もう1件、新しく始める' : 'この手続きを始める'}
              </h2>
              <p className='text-std-16N-170 text-solid-gray-700'>
                案内ウィザードに沿って条件を選ぶと、必要書類を揃えた案件を作成します。
              </p>
              <div>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='md'
                  onClick={onStart}
                >
                  この手続きを始める
                </Button>
              </div>
            </section>
          </>
        ) : null}

        <p className='text-std-16N-170'>
          <Link to='/patchform/my' className='text-blue-900 underline-offset-2 hover:underline'>
            マイ手続きへ
          </Link>
        </p>
      </div>
    </LayoutBody>
  );
};
