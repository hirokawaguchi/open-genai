import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import {
  downloadProcedureLinkFile,
  downloadProcedureQr,
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
  const { share, isLoading, loadError } = usePatchformProcedureShare(procedureId, open);

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
              <p className='text-dns-14N-130 text-solid-gray-600'>
                この手続きは庁内のみです。庁外向けのURLとQRはありません。
              </p>
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
