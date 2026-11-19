import type { ComponentProps } from 'react';

export type PresentationIconProps = ComponentProps<'svg'>;

export const PresentationIcon = (props: PresentationIconProps) => {
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
        d='M80-160v-80h800v80H80Zm160-160q-33 0-56.5-23.5T160-400v-320q0-33 23.5-56.5T240-800h480q33 0 56.5 23.5T800-720v320q0 33-23.5 56.5T720-320H240Zm0-80h480v-320H240v320Zm0 0v-320 320Z'
        fill='currentColor'
      />
    </svg>
  );
};
