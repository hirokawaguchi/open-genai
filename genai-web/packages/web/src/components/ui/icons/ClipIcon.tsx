import type { ComponentProps } from 'react';

export type ClipIconProps = ComponentProps<'svg'>;

export const ClipIcon = (props: ClipIconProps) => {
  const { className, ...rest } = props;
  return (
    <svg
      className={`${className ?? ''}`}
      width='24'
      height='24'
      viewBox='0 -960 960 960'
      fill='none'
      {...rest}
    >
      <path
        d='M200-120v-640q0-33 23.5-56.5T280-840h400q33 0 56.5 23.5T760-760v640L480-240 200-120Zm80-122 200-86 200 86v-518H280v518Zm0-518h400-400Z'
        fill='currentColor'
      />
    </svg>
  );
};
