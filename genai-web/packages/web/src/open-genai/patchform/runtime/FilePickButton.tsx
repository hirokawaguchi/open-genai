import { useRef, type ChangeEvent } from 'react';
import { Button } from '@/components/ui/dads/Button';

type Props = {
  id?: string;
  accept?: string;
  disabled?: boolean;
  busy?: boolean;
  filename?: string;
  buttonLabel?: string;
  error?: string | null;
  onFile: (file: File | null) => void;
};

/** ネイティブ file input の代わりに、他アプリと同じ「ファイルを選択」ボタンを出す。 */
export const FilePickButton = ({
  id,
  accept,
  disabled,
  busy,
  filename,
  buttonLabel = 'ファイルを選択',
  error,
  onFile,
}: Props) => {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    onFile(e.target.files?.[0] ?? null);
  };

  return (
    <div className='mt-1 flex flex-wrap items-center gap-3'>
      <input
        id={id}
        ref={inputRef}
        type='file'
        accept={accept}
        className='sr-only'
        disabled={disabled || busy}
        onChange={handleChange}
      />
      <Button
        type='button'
        variant='outline'
        size='md'
        aria-disabled={disabled || busy || undefined}
        onClick={() => inputRef.current?.click()}
      >
        {busy ? 'アップロード中...' : buttonLabel}
      </Button>
      <p className='text-std-16N-170 text-solid-gray-700'>
        {filename ? `選択中: ${filename}` : '選択されていません'}
      </p>
      {error ? (
        <p className='w-full text-dns-14N-130 text-error-1' role='alert'>
          {error}
        </p>
      ) : null}
    </div>
  );
};
