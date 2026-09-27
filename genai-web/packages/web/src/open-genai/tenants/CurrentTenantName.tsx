import type { ComponentProps } from 'react';
import { useMyTenants } from './useTenants';

export const OrgIcon = (props: ComponentProps<'svg'>) => {
  const { className, ...rest } = props;
  return (
    <svg
      aria-hidden={true}
      className={`shrink-0 ${className ?? ''}`}
      fill='currentColor'
      height='20'
      viewBox='0 -960 960 960'
      width='20'
      {...rest}
    >
      <path d='M80-120v-720h400v160h400v560H80Zm80-80h240v-80H160v80Zm0-160h240v-80H160v80Zm0-160h240v-80H160v80Zm0-160h240v-80H160v80Zm320 480h320v-400H480v400Zm80-240v-80h160v80H560Zm0 160v-80h160v80H560Z' />
    </svg>
  );
};

export const CurrentTenantName = () => {
  const { switchableTenants, activeTenantId, isLoading } = useMyTenants();
  if (isLoading) {
    return null;
  }
  const current =
    switchableTenants.find((t) => t.tenantId === activeTenantId) ?? switchableTenants[0];
  if (!current?.tenantName) {
    return null;
  }
  return (
    <span className='inline-flex items-center gap-1 px-2 text-dns-14N-130 text-solid-gray-700'>
      <OrgIcon />
      <span className='sr-only'>組織 </span>
      {current.tenantName}
    </span>
  );
};
