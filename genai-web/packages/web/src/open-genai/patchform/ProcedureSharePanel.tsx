import { useState } from 'react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import {
  downloadProcedureLinkFile,
  downloadProcedureQr,
  usePatchformProcedureActions,
  usePatchformProcedureShare,
} from './usePatchform';

const svgSrc = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

const copyText = async (value: string) => {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
};

const QrBlock = ({
  title,
  hint,
  url,
  svg,
  filename,
}: {
  title: string;
  hint: string;
  url: string;
  svg: string;
  filename: string;
}) => {
  const [copied, setCopied] = useState(false);
  return (
    <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 bg-white px-3 py-3 sm:flex-row sm:items-start sm:gap-4'>
      <img src={svgSrc(svg)} alt={`${title}のQRコード`} className='size-32 shrink-0 bg-white' />
      <div className='flex min-w-0 flex-1 flex-col gap-2'>
        <p className='text-std-16B-150'>{title}</p>
        <p className='text-dns-14N-130 text-solid-gray-600'>{hint}</p>
        <p className='break-all text-dns-14N-130 text-solid-gray-800'>{url}</p>
        <div className='flex flex-wrap gap-2'>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={async () => {
              const ok = await copyText(url);
              setCopied(ok);
            }}
          >
            {copied ? 'コピーしました' : 'URLをコピー'}
          </Button>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={() => downloadProcedureQr(filename, svg)}
          >
            QRを保存
          </Button>
        </div>
      </div>
    </div>
  );
};

export const ProcedureSharePanel = ({
  procedureId,
  name,
}: {
  procedureId: string;
  name: string;
}) => {
  const [open, setOpen] = useState(false);
  const { share, isLoading, loadError, mutate } = usePatchformProcedureShare(procedureId, open);
  const { setGuideVisibility, submitting } = usePatchformProcedureActions();
  const [fixError, setFixError] = useState<string | null>(null);

  // 庁外URLは案内（ナビゲーション）フォームの公開範囲が「庁内と外部」「外部のみ」の
  // ときだけ作られる。庁内のみだと庁外導線が出ないので、その場で公開範囲を広げられる。
  const onOpenExternal = async () => {
    setFixError(null);
    const updated = await setGuideVisibility(procedureId, 'both');
    if (updated) {
      await mutate();
    } else {
      setFixError('案内フォームの公開範囲を変更できませんでした。時間をおいて再度お試しください。');
    }
  };

  return (
    <Disclosure
      className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-3 py-2'
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <DisclosureSummary>
        <span className='text-std-16B-150'>申請用リンクとQRコード</span>
      </DisclosureSummary>
      <div className='mt-3 flex flex-col gap-3'>
        {isLoading ? <p className='text-solid-gray-600'>読み込み中...</p> : null}
        {loadError ? (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        ) : null}
        {share ? (
          <>
            <QrBlock
              title='庁内'
              hint='ログインした職員が、最初の様式を開けます。このURLを共有・掲示できます。'
              url={share.internal_url}
              svg={share.internal_qr_svg}
              filename={`${name}_庁内QR.svg`}
            />
            {share.external_url && share.external_qr_svg ? (
              <QrBlock
                title='庁外'
                hint='申請者や回答者が、公開の入力画面を開けます。'
                url={share.external_url}
                svg={share.external_qr_svg}
                filename={`${name}_庁外QR.svg`}
              />
            ) : (
              <div className='flex flex-col gap-2 rounded-8 border border-amber-600 bg-amber-50 px-3 py-3'>
                <p className='text-std-16B-150 text-amber-900'>
                  庁外向けのURL・QRがありません
                </p>
                <p className='text-dns-14N-130 text-solid-gray-800'>
                  入口となる<strong>案内（ナビゲーション）フォームの公開範囲が「庁内のみ」</strong>のため、庁外には公開できません。庁外にも公開するには、案内フォームの公開範囲を「庁内と外部」に変更してください。
                </p>
                {fixError && (
                  <p className='text-error-1' role='alert'>
                    {fixError}
                  </p>
                )}
                <div className='flex flex-wrap gap-2'>
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='sm'
                    aria-disabled={submitting}
                    onClick={() => void onOpenExternal()}
                  >
                    {submitting ? '変更中...' : '庁外にも公開する'}
                  </Button>
                  {share.guide_form_id && (
                    <Link to={`/patchform/${share.guide_form_id}/edit`} className='inline-flex'>
                      <Button type='button' variant='outline' size='sm'>
                        案内フォームを編集
                      </Button>
                    </Link>
                  )}
                </div>
              </div>
            )}
            <div>
              <Button
                type='button'
                variant='outline'
                size='sm'
                onClick={() =>
                  downloadProcedureLinkFile(name, {
                    internal: share.internal_url,
                    external: share.external_url,
                  })
                }
              >
                リンクファイル
              </Button>
            </div>
          </>
        ) : null}
      </div>
    </Disclosure>
  );
};
