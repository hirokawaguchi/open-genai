type Props = {
  className?: string;
  checked: boolean;
  onSwitch: (newValue: boolean) => void;
  label: string;
  disabled?: boolean;
  title?: string;
};

export const Switch = (props: Props) => {
  const { className, checked, onSwitch, label, disabled, title } = props;
  return (
    <div className={`${className ?? ''}`}>
      <label
        title={title}
        className={`relative inline-flex items-center gap-1.5 ${
          disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:underline'
        }`}
      >
        <input
          type='checkbox'
          role='switch'
          value=''
          className='peer absolute inset-0 z-10 m-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed'
          checked={checked}
          disabled={disabled}
          onMouseDown={(event) => {
            // 画面外の入力へフォーカスが移ると、ブラウザがそこへスクロールする。
            event.preventDefault();
          }}
          onChange={() => {
            if (disabled) return;
            onSwitch(!checked);
          }}
        />
        <span
          className={`relative block h-7 w-12 rounded-[calc(infinity*1px)] border-2 border-transparent bg-solid-gray-420 peer-checked:bg-blue-900 peer-focus-visible:ring-[calc(2/16*1rem)] peer-focus-visible:ring-yellow-300 peer-focus-visible:outline-4 peer-focus-visible:outline-offset-[calc(2/16*1rem)] peer-focus-visible:outline-black peer-focus-visible:outline-solid before:m-0.5 before:block before:size-5 before:rounded-full before:bg-white before:transition-transform before:content-[''] peer-checked:before:translate-x-full after:absolute after:inset-x-0 after:-inset-y-full after:m-auto after:h-11 forced-colors:border-[ButtonBorder] forced-colors:peer-checked:border-[Highlight] forced-colors:peer-checked:bg-[Highlight] forced-colors:before:bg-[Highlight] forced-colors:peer-checked:before:bg-[Canvas]`}
        />
        <span className='text-oln-16N-100'>{label}</span>
      </label>
    </div>
  );
};
