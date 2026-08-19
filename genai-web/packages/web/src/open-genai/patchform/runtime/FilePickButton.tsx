import { useRef, type ChangeEvent } from 'react';
import { Button } from '@/components/ui/dads/Button';

type Props = {
  id?: string;
  accept?: string;
  disabled?: boolean;
  filename?: string;
  buttonLabel?: string;
  onFile: (file: File | null) => void;
};

/** ネイティブ file input の代わりに、他アプリと同じ「ファイルを選択」ボタンを出す。 */
export const FilePickButton = ({
  id,
  accept,
  disabled,
  filename,
  buttonLabel = 'ファイルを選択',
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
        disabled={disabled}
        onChange={handleChange}
      />
      <Button
        type='button'
        variant='outline'
        size='md'
        aria-disabled={disabled || undefined}
        onClick={() => inputRef.current?.click()}
      >
        {buttonLabel}
      </Button>
      <p className='text-std-16N-170 text-solid-gray-700'>
        {filename ? `選択中: ${filename}` : '選択されていません'}
      </p>
    </div>
  );
};
