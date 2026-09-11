import { Radio } from '@/components/ui/dads/Radio';
import { useSubmitKey } from '@/hooks/useSubmitKey';
import { SUBMIT_KEY_OPTIONS, type SubmitKey } from '@/utils/keyboard';

export const SubmitKeySettings = () => {
  const { key, setKey } = useSubmitKey();

  return (
    <fieldset className='flex flex-col gap-1 border-0 p-0 m-0'>
      <legend className='sr-only'>送信キー</legend>
      {SUBMIT_KEY_OPTIONS.map((opt) => (
        <Radio
          key={opt.value}
          name='submitKey'
          value={opt.value}
          size='md'
          checked={key === opt.value}
          onChange={() => setKey(opt.value as SubmitKey)}
        >
          <span className='flex flex-col gap-0.5'>
            <span>{opt.label}</span>
            <span className='text-dns-14N-130 text-solid-gray-600'>{opt.description}</span>
          </span>
        </Radio>
      ))}
    </fieldset>
  );
};
