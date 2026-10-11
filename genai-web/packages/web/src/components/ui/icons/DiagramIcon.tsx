import type { ComponentProps } from 'react';

export type DiagramIconProps = ComponentProps<'svg'>;

export const DiagramIcon = (props: DiagramIconProps) => {
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
        d='M640-120v-120H520v-160h120v-120h-80v-80h80v-120H480v120h80v80h-80v320H320v-80h80v-80h-80v-120h80v-120H160v120h80v80h-80v120h80v80h-80v200h240v120h160Zm80-80h80v-80h-80v80ZM200-680h80v-80h-80v80Zm0 200h80v-80h-80v80Zm0 200h80v-80h-80v80Zm480-200h80v-80h-80v80Z'
        fill='currentColor'
      />
    </svg>
  );
};
