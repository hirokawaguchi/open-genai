import { Select } from '@/components/ui/dads/Select';
import { useMyTenants, useTenantActions } from './useTenants';

export const TenantSwitcher = () => {
  const { switchableTenants, activeTenantId, canSwitchTenants, isLoading } = useMyTenants();
  const { setActive } = useTenantActions();

  if (isLoading || !canSwitchTenants) {
    return null;
  }

  const value = switchableTenants.some((t) => t.tenantId === activeTenantId)
    ? (activeTenantId ?? switchableTenants[0]?.tenantId ?? '')
    : (switchableTenants[0]?.tenantId ?? '');

  return (
    <label className='flex items-center gap-2 px-2 text-dns-14N-130 text-solid-gray-800'>
      <Select
        aria-label='利用する組織'
        className='min-w-40 max-w-56'
        value={value}
        onChange={(e) => {
          const next = e.target.value;
          if (next && next !== activeTenantId) {
            void setActive(next);
          }
        }}
      >
        {switchableTenants.map((t) => (
          <option key={t.tenantId} value={t.tenantId}>
            {t.tenantName}
          </option>
        ))}
      </Select>
    </label>
  );
};
