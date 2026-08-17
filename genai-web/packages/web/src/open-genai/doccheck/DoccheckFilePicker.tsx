import { useRef, type ChangeEvent } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';

type Props = {
  id: string;
  label: string;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  files: FileList | null;
  buttonLabel?: string;
  onChange: (files: FileList | null) => void;
};

/**
 * ネイティブ file input は OS 依存で見た目が崩れるため、Button + 選択状態表示に寄せる。
 */
export const DoccheckFilePicker = ({
  id,
  label,
  accept = 'image/*',
  multiple,
  disabled,
  files,
  buttonLabel = 'ファイルを選択',
  onChange,
}: Props) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const names = files ? Array.from(files).map((f) => f.name) : [];

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.files);
  };

  return (
    <div className='flex flex-col gap-1.5'>
      <Label htmlFor={id} size='sm'>
        {label}
      </Label>
      <input
        id={id}
        ref={inputRef}
        type='file'
        accept={accept}
        multiple={multiple}
        className='sr-only'
        onChange={handleChange}
      />
      <div className='flex flex-wrap items-center gap-3'>
        <Button
          type='button'
          variant='outline'
          size='md'
          aria-disabled={disabled || undefined}
          onClick={() => inputRef.current?.click()}
        >
          {buttonLabel}
        </Button>
        <p className='text-std-14N-170 text-solid-gray-700'>
          {names.length > 0
            ? multiple
              ? `選択中: ${names.length} 件（${names.slice(0, 3).join('、')}${
                  names.length > 3 ? ' …' : ''
                }）`
              : `選択中: ${names[0]}`
            : '選択されていません'}
        </p>
      </div>
    </div>
  );
};
